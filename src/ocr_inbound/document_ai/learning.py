"""Offline, review-only product retrieval and pairwise ranking.

No OCR, database, alias activation or model fitting happens during inference.
Teacher identities are business labels, never glyph transcription targets.
V1 features cover names, explicit specifications and exact identifiers only;
supplier, chronology and invoice co-occurrence are not model features.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
import subprocess
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

SCHEMA = "document-ai-product-ranker.v1"
FEATURES = ("name_similarity", "gram_overlap", "token_overlap", "number_overlap",
            "strength_agreement", "strength_conflict", "form_agreement", "form_conflict",
            "pack_agreement", "pack_conflict", "exact_company_code", "exact_barcode")
DEFAULT_WEIGHTS = (2.5, 2.0, 1.0, .25, .8, -5., .5, -4., .5, -3., 6., 6.)


def normalize(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).lower()).strip()


def grams(value):
    text = re.sub(r"\W", "", normalize(value))
    return {text[i:i + 3] for i in range(max(1, len(text) - 2))} if text else set()


def _overlap(a, b):
    return len(a & b) / max(1, len(a | b))


def specifications(text):
    """Conservative explicit specifications; missing values do not mean agreement."""
    text = normalize(text)
    replacements = {"ไมโครกรัม": "mcg", "มคก": "mcg", "มิลลิกรัม": "mg", "มก": "mg",
                    "มิลลิลิตร": "ml", "มล": "ml", "กรัม": "g", "ซีซี": "ml", "cc": "ml"}
    for a, b in replacements.items():
        text = text.replace(a, b)
    strengths = set()
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(mcg|mg|ml|g|%)(?![a-z])", text):
        n = float(number)
        if unit == "mcg":
            n, unit = n / 1000, "mg"
        elif unit == "g":
            n, unit = n * 1000, "mg"
        strengths.add((round(n, 7), unit))
    forms = set()
    for canonical, pattern in {
        "cream": r"cream|ครีม", "gel": r"\bgel\b|เจล", "ointment": r"ointment|ขี้ผึ้ง",
        "lotion": r"lotion|โลชั่น", "tablet": r"\btab(?:let)?s?\b|เม็ด",
        "capsule": r"\bcap(?:sule)?s?\b|แคปซูล", "syrup": r"syrup|ไซรัป|ยาน้ำ",
        "spray": r"spray|สเปรย์", "drop": r"\bdrops?\b|ยาหยอด",
    }.items():
        if re.search(pattern, text):
            forms.add(canonical)
    packs = set()
    for a, b in re.findall(r"(\d+)\s*[x*×]\s*(\d+)", text):
        packs.add(int(a) * int(b))
    for n in re.findall(r"(\d+)\s*(?:เม็ด|แคปซูล|ชิ้น|แผ่น|\b['’]?s\b)", text):
        packs.add(int(n))
    return {"strength": strengths, "form": forms, "pack": packs}


def canonical_product(row):
    code = row.get("code") or row.get("FTPdtCode") or row.get("product_code")
    names = row.get("names") or [row.get("name") or row.get("FTPdtName") or "",
                                 row.get("english_name") or row.get("FTPdtNameOth") or ""]
    barcodes = row.get("barcodes") or [row.get(k) for k in
                   ("barcode", "FTPdtBarCode1", "FTPdtBarCode2", "FTPdtBarCode3")]
    return {"code": str(code or ""), "names": list(dict.fromkeys(str(n) for n in names if n)),
            "barcodes": sorted(set(str(b) for b in barcodes if b)),
            "source": row.get("source", "saved_catalogue_snapshot")}


class ProductMatcher:
    def __init__(self, catalog, model=None):
        self.catalog = [canonical_product(p) for p in catalog]
        self.by_code = {p["code"]: p for p in self.catalog}
        if len(self.by_code) != len(self.catalog) or "" in self.by_code:
            raise ValueError("Catalogue codes must be nonempty and unique")
        self.model = model or {}
        if model and (model.get("schema") != SCHEMA or model.get("features") != list(FEATURES)):
            raise ValueError("Ranker schema/feature contract mismatch")
        self.weights = self.model.get("weights", DEFAULT_WEIGHTS)
        if len(self.weights) != len(FEATURES) or not all(math.isfinite(float(v)) for v in self.weights):
            raise ValueError("Invalid ranker weights")
        self.index = defaultdict(set)
        self.exact_barcodes = defaultdict(set)
        self.prepared = {}
        for p in self.catalog:
            text = " ".join(p["names"])
            self.prepared[p["code"]] = (grams(text), specifications(text))
            for g in grams(text):
                self.index[g].add(p["code"])
            for b in p["barcodes"]:
                self.exact_barcodes[b].add(p["code"])

    def _exact(self, query, product):
        # A supplier item number is deliberately not an internal company code.
        trusted = query.get("identifier_evidence") == "source_exact"
        code = trusted and bool(query.get("company_code")) and query["company_code"] == product["code"]
        barcode = trusted and bool(query.get("barcode")) and query["barcode"] in product["barcodes"]
        return bool(code), bool(barcode)

    def feature_vector(self, query, product):
        name = str(query.get("description") or "")
        qgrams, qspec = grams(name), specifications(name)
        pgrams, pspec = self.prepared[product["code"]]
        best_name = max((SequenceMatcher(None, normalize(name), normalize(n), autojunk=False).ratio()
                         for n in product["names"]), default=0.)
        ptokens = set(normalize(" ".join(product["names"])).split())
        qtokens = set(normalize(name).split())
        nums = lambda s: set(re.findall(r"\d+(?:\.\d+)?", s))
        vals = [best_name, _overlap(qgrams, pgrams), _overlap(qtokens, ptokens),
                _overlap(nums(name), nums(" ".join(product["names"])))]
        explanations = {"description": {"raw": name, "catalogue_names": product["names"],
                                         "similarity": round(best_name, 6)}}
        blocks = []
        for field in ("strength", "form", "pack"):
            q, p = qspec[field], pspec[field]
            comparable = bool(q and p)
            agreement, conflict = comparable and bool(q & p), comparable and not bool(q & p)
            vals.extend([float(agreement), float(conflict)])
            explanations[field] = {"source": sorted(q), "catalogue": sorted(p),
                                   "status": "conflict" if conflict else "agreement" if agreement else "unknown"}
            if conflict:
                blocks.append(field + "_conflict")
        code, barcode = self._exact(query, product)
        vals.extend([float(code), float(barcode)])
        explanations["identifiers"] = {"exact_company_code": code, "exact_barcode": barcode,
                                        "supplier_code_used_as_company_code": False}
        return vals, blocks, explanations

    def retrieve(self, query, limit=30):
        counts = Counter()
        for g in grams(query.get("description", "")):
            counts.update(self.index.get(g, ()))
        codes = [c for c, _ in counts.most_common(max(limit * 3, 80))]
        if query.get("identifier_evidence") == "source_exact":
            if query.get("company_code") in self.by_code:
                codes.append(query["company_code"])
            codes.extend(sorted(self.exact_barcodes.get(query.get("barcode"), ())))
        scored = []
        for code in dict.fromkeys(codes):
            p = self.by_code[code]
            vector, blocks, explanation = self.feature_vector(query, p)
            scored.append({"code": code, "score": sum(w * v for w, v in zip(self.weights, vector)),
                           "features": dict(zip(FEATURES, vector)), "blocks": blocks,
                           "field_explanations": explanation, "names": p["names"]})
        return sorted(scored, key=lambda r: (-r["score"], r["code"]))[:limit]

    def match(self, query):
        candidates = self.retrieve(query)
        result = {"status": "ABSTAIN", "proposed_code": None, "review_required": True,
                  "production_ready": False, "candidates": candidates[:5], "reasons": []}
        if query.get("catalogue_pending") or query.get("known_new_item"):
            result["reasons"] = ["known_catalogue_absence_or_new_item"]
            return result
        if not candidates:
            result["reasons"] = ["no_retrieval_evidence"]
            return result
        top = candidates[0]
        exact_ids = set()
        if query.get("identifier_evidence") == "source_exact":
            if query.get("company_code"):
                exact_ids.add(query["company_code"])
            exact_ids.update(self.exact_barcodes.get(query.get("barcode"), ()))
        if len(exact_ids) > 1:
            result["reasons"] = ["conflicting_or_nonunique_exact_identifiers"]
            return result
        if query.get("identifier_evidence") == "source_exact":
            if ((query.get("company_code") and query["company_code"] not in self.by_code) or
                    (query.get("barcode") and not self.exact_barcodes.get(query["barcode"]))):
                result["reasons"] = ["trusted_identifier_absent_from_catalogue"]
                return result
        if len(exact_ids) == 1 and next(iter(exact_ids)) in self.by_code:
            _, exact_blocks, _ = self.feature_vector(query, self.by_code[next(iter(exact_ids))])
            if exact_blocks:
                result["reasons"] = exact_blocks
                return result
        if exact_ids and top["code"] not in exact_ids:
            result["reasons"] = ["exact_identifier_and_name_disagree"]
            return result
        if top["blocks"]:
            result["reasons"] = top["blocks"]
            return result
        exact = top["features"]["exact_company_code"] or top["features"]["exact_barcode"]
        margin = top["score"] - candidates[1]["score"] if len(candidates) > 1 else top["score"]
        result["margin"] = margin
        if not exact and (top["features"]["name_similarity"] < .56 or top["features"]["gram_overlap"] < .18):
            result["reasons"] = ["weak_or_unknown_product_name"]
        elif not exact and margin < self.model.get("minimum_margin", .35):
            result["reasons"] = ["ambiguous_neighbour"]
        else:
            result.update(status="CANDIDATE", proposed_code=top["code"], reasons=["review_only_identity_proposal"])
        return result


def group_split(group_id):
    bucket = int(hashlib.sha256(("document-ai-split-v1:" + group_id).encode()).hexdigest()[:8], 16) % 100
    return "test" if bucket < 15 else "validation" if bucket < 30 else "train"


def require_hq():
    addresses = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None)}
    if "100.90.166.72" not in addresses and os.name == "nt":
        # Windows DNS can expose only the LAN address; inspect the local
        # adapter addresses as well, without trusting a caller-supplied flag.
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                                 "Get-NetIPAddress -AddressFamily IPv4 | Select-Object -ExpandProperty IPAddress"],
                                capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode == 0:
            addresses.update(result.stdout.split())
    if "100.90.166.72" not in addresses:
        raise RuntimeError("Fitting is restricted to HQ server 100.90.166.72; this host is not HQ")


def fit_pairwise(catalog, examples, *, epochs=20, learning_rate=.03, checkpoint_callback=None):
    """Bounded RankNet-style linear learning-to-rank; call on HQ only.

    Retrieval neighbours include wrong strength/form/pack as hard negatives.
    Only manifest train examples enter updates; no test/validation adaptation.
    """
    require_hq()
    matcher = ProductMatcher(catalog)
    pairs = []
    hard_counts = Counter()
    training_ids = []
    for e in examples:
        if not e.get("eligible") or e.get("split") != "train" or not e.get("target_code"):
            continue
        target = matcher.by_code.get(e["target_code"])
        if target is None:
            continue
        positive, _, _ = matcher.feature_vector(e["query"], target)
        negatives = [c for c in matcher.retrieve(e["query"], 20) if c["code"] != target["code"]]
        # Prioritize semantically dangerous near neighbours, then closest names.
        negatives.sort(key=lambda c: (not bool(c["blocks"]), -c["features"]["name_similarity"]))
        for n in negatives[:8]:
            pairs.append(([a - b for a, b in zip(positive, n["features"].values())], float(e.get("weight", .5)), e["id"]))
            hard_counts.update(n["blocks"])
        if negatives:
            training_ids.append(e["id"])
    if not pairs:
        raise ValueError("No eligible training pairs")
    weights = list(DEFAULT_WEIGHTS)
    updates = 0
    actual_ids = set()
    def snapshot(epoch, final=False):
        if not all(math.isfinite(w) for w in weights):
            raise FloatingPointError("Nonfinite ranker weights; last valid checkpoint preserved")
        return {"schema": SCHEMA, "features": list(FEATURES), "weights": list(weights),
                "minimum_margin": .35, "host_constraint": "100.90.166.72", "epochs": epochs,
                "completed_epochs": epoch, "final": final, "actual_updates": updates,
                "actual_pairs": min(updates, len(pairs)), "planned_pairs_per_epoch": len(pairs),
                "actual_examples": len(actual_ids), "training_example_ids": sorted(actual_ids),
                "planned_training_example_ids": training_ids,
                "hard_negative_conflicts": dict(hard_counts), "all_weights_finite": True,
                "feature_scope": "names_specifications_exact_identifiers_only_no_supplier_time_cooccurrence",
                "label_contract": "identity_business_labels_not_printed_glyph_truth", "production_ready": False}
    for epoch in range(epochs):
        for delta, authority_weight, example_id in pairs:
            score = sum(a * b for a, b in zip(weights, delta))
            gradient = authority_weight / (1 + math.exp(max(-40., min(40., score))))
            weights = [w + learning_rate * (gradient * d - .001 * w) for w, d in zip(weights, delta)]
            updates += 1
            actual_ids.add(example_id)
            if checkpoint_callback is not None and updates % 256 == 0:
                checkpoint_callback(snapshot(updates // len(pairs)))
        if checkpoint_callback is not None and len(pairs) < 256 and updates % 256 != 0:
            checkpoint_callback(snapshot(epoch + 1))
    model = snapshot(epochs, final=True)
    if checkpoint_callback is not None:
        checkpoint_callback(model)
    return model


def evaluate(matcher, examples):
    aggregates, suppliers = defaultdict(Counter), defaultdict(Counter)
    cases = []
    for e in examples:
        if not e.get("eligible"):
            continue
        result = matcher.match(e["query"])
        target = e.get("target_code")
        top = result["candidates"][0]["code"] if result["candidates"] else None
        metric = {"examples": 1, "top1_correct": int(top == target and target is not None),
                  "proposed": int(result["proposed_code"] is not None),
                  "correct_proposal": int(result["proposed_code"] == target and target is not None),
                  "wrong_proposal": int(result["proposed_code"] is not None and result["proposed_code"] != target),
                  "abstained": int(result["status"] == "ABSTAIN"),
                  "unknown_examples": int(target is None),
                  "unknown_false_accept": int(target is None and result["proposed_code"] is not None)}
        aggregates[e["split"]].update(metric)
        suppliers[e.get("supplier", "unknown")].update(metric)
        cases.append({"id": e["id"], "supplier": e.get("supplier"), "split": e["split"],
                      "authority": e["authority"], "target": target, "result": result})
    return {"split_metrics": dict(aggregates), "supplier_metrics": dict(suppliers), "cases": cases,
            "unseen_accuracy_claim": False, "whole_row_human_gold": 0}


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
