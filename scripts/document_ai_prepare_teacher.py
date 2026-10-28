"""Prepare frozen private identity teachers; baseline, then fit/evaluate on HQ.

Example: python scripts/document_ai_prepare_teacher.py prepare --facts ...
 --reconciliation ... --catalogue ... --user-confirmations ... --out ...
No image is opened and no OCR is called. Private inputs/outputs stay out of Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ocr_inbound.document_ai.learning import (ProductMatcher, canonical_product, evaluate,
    file_sha256, fit_pairwise, group_split, load_json, require_hq)


def write_new(path, payload):
    """Flush a sibling temporary file, then publish atomically and exclusively.

    Hard-link publication never exposes partially written JSON and never
    replaces an existing manifest/checkpoint. A killed writer may leave its
    clearly named temporary file; a published checkpoint remains complete.
    """
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_name, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        os.unlink(temp_name)


def checkpoint_writer(folder, metadata):
    """Create a fresh checkpoint namespace and fsynced append-only trace."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    def publish(checkpoint):
        checkpoint = dict(checkpoint, **metadata)
        stem = "final_step" if checkpoint["final"] else "step"
        path = folder / (stem + "_%09d.json" % checkpoint["actual_updates"])
        write_new(path, checkpoint)
        record = {"checkpoint": path.name, "sha256": file_sha256(path),
                  "actual_updates": checkpoint["actual_updates"], "actual_pairs": checkpoint["actual_pairs"],
                  "actual_examples": checkpoint["actual_examples"], "completed_epochs": checkpoint["completed_epochs"],
                  "training_example_ids": checkpoint["training_example_ids"], "final": checkpoint["final"],
                  "all_weights_finite": checkpoint["all_weights_finite"], **metadata}
        with (folder / "trace.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return publish


def raw_machine_field(field):
    if not isinstance(field, dict):
        return None
    # Never replace raw OCR with an assistant's visual source proposal.
    if isinstance(field.get("raw_ocr_field"), dict):
        return raw_machine_field(field["raw_ocr_field"])
    engine = str(field.get("engine", "")).upper()
    if any(t in engine for t in ("ASSISTANT", "VISUAL", "USER", "MASTER", "SQL")):
        return None
    if not any(t in engine for t in ("PADDLE", "TESSERACT", "TESS", "OCR")):
        return None
    value = field.get("raw_value")
    return {"value": str(value), "engine": field.get("engine"), "bbox": field.get("bbox"),
            "token_ids": field.get("token_ids", [])} if value not in (None, "") else None


def build_examples(facts, reconciliation, user_confirmations, catalogue):
    final = {r["id"]: r for r in reconciliation.get("rows", [])}
    known_codes = {p["code"] for p in catalogue}
    # Union source hashes and invoice/receipt identifiers BEFORE any split.
    # A continuation page or duplicate source event cannot cross partitions.
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)
    row_groups = {}
    for row in facts:
        r = final.get(row["id"], {})
        source = "source:" + row.get("source_sha256", row.get("source_file", row["id"]))
        supplier = row.get("supplier_layout_key", "unknown")
        keys = [source]
        header = row.get("receipt_header") or {}
        for role, value in (("receipt", header.get("FTXihDocNo")),
                            ("invoice", header.get("FTXihRefExt")),
                            ("invoice", r.get("invoice_candidate")), ("receipt", r.get("receipt"))):
            if value:
                keys.append(role + ":" + supplier + ":" + str(value))
        for k in keys:
            union(source, k)
        row_groups[row["id"]] = source
    output = []
    source_group_labels = defaultdict(set)
    user_records = {r["row_id"]: r for r in user_confirmations.get("latest_16_review", {}).get("records", [])}
    for row in facts:
        r = final.get(row["id"], {})
        fields = (row.get("scan_row") or {}).get("fields") or {}
        description = raw_machine_field(fields.get("description"))
        supplier_code = raw_machine_field(fields.get("supplier_code"))
        code = row.get("company_sku")
        status = row.get("sku_match_status", "")
        evidence = row.get("receipt_match_evidence") or {}
        receipt_line = evidence.get("receipt_line") or {}
        pending = bool(row.get("catalogue_pending_excluded") or
                       r.get("group") == "NEW_PRODUCT_CATALOGUE_PENDING" or
                       status in ("USER_REPORTED_NEW_PRODUCT_NOT_YET_KEYED", "USER_CONFIRMED_NOT_YET_IN_ADA_CATALOGUE"))
        reason, authority, weight = "uncorroborated_or_unconfirmed_proposal", "unconfirmed", 0.
        eligible = False
        if pending:
            code, authority, reason = None, "user_reported_catalogue_absence", "known_unknown_control"
            eligible = True
        elif status == "USER_CONFIRMED_ROW_SCOPED_PRODUCT_IDENTITY" and code in known_codes:
            authority, reason, weight, eligible = "user_row_identity_only", "identity_only_not_full_row_approval", 1., True
        elif (status == "STRONG_CANDIDATE" and code in known_codes and
              receipt_line.get("FTPdtCode") == code and not evidence.get("specification_conflicts")):
            authority, reason, weight, eligible = "receipt_corroborated_llm_silver", "saved_teacher_and_receipt_code_agree", .5, True
        if not description:
            eligible, reason = False, "no_machine_description_evidence"
        if not row.get("source_sha256"):
            eligible, reason = False, "missing_source_hash"
        group = find(row_groups[row["id"]])
        query = {"description": description["value"] if description else "",
                 "supplier_code": supplier_code["value"] if supplier_code else None,
                 "catalogue_pending": pending}
        e = {"id": row["id"], "supplier": row.get("supplier_layout_key", "unknown"),
             "source_sha256": row.get("source_sha256"), "source_file": row.get("source_file"),
             "source_group_id": row.get("source_group_id"), "dependency_group": group,
             "split": group_split(group), "query": query, "query_evidence": description,
             "target_code": code, "authority": authority, "weight": weight,
             "eligible": eligible, "eligibility_reason": reason,
             "saved_teacher_status": status, "human_whole_row_verified": row.get("human_verified", False),
             "printed_source_proposal": {"description": (fields.get("description") or {}).get("raw_value"),
                                         "engine": (fields.get("description") or {}).get("engine")},
             "business_identity_evidence": {"receipt_code": receipt_line.get("FTPdtCode"),
                         "receipt_document": receipt_line.get("FTXihDocNo"),
                         "specification_conflicts": evidence.get("specification_conflicts", [])},
             "user_attestation": user_records.get(row["id"], {}).get("user_strength_attestation"),
             "glyph_training_eligible": False}
        output.append(e)
        if eligible and code:
            source_group_labels[row.get("source_group_id") or row["id"]].add(code)
    # Conflicting mappings of a shared source event remain quarantined.
    for e in output:
        if len(source_group_labels[e["source_group_id"] or e["id"]]) > 1:
            e.update(eligible=False, eligibility_reason="conflicting_source_event_identity")
    return output


def prepare(args):
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("Use a fresh output directory; frozen training manifests are never overwritten")
    out.mkdir(parents=True, exist_ok=True)
    facts = load_json(args.facts)["rows"]
    snapshot = load_json(args.catalogue)
    catalogue = [canonical_product(r) for r in snapshot["productMaster"]]
    if len({p["code"] for p in catalogue}) != len(catalogue):
        raise ValueError("Duplicate catalogue code")
    examples = build_examples(facts, load_json(args.reconciliation), load_json(args.user_confirmations), catalogue)
    counts = Counter(e["authority"] for e in examples)
    eligible = [e for e in examples if e["eligible"]]
    summaries = {"source_rows": len(facts), "catalogue_products": len(catalogue),
                 "authority_all_rows": dict(counts), "eligible_examples": len(eligible),
                 "eligible_by_authority": dict(Counter(e["authority"] for e in eligible)),
                 "eligible_by_split": dict(Counter(e["split"] for e in eligible)),
                 "quarantine_reasons": dict(Counter(e["eligibility_reason"] for e in examples if not e["eligible"])),
                 "whole_row_human_gold": sum(bool(e["human_whole_row_verified"]) for e in examples),
                 "glyph_training_examples": 0, "all_data_known_development": True,
                 "independent_new_invoice_accuracy": False}
    write_new(out / "catalogue.json", catalogue)
    write_new(out / "examples.json", examples)
    sources = {k: {"path": str(Path(getattr(args, k)).resolve()), "sha256": file_sha256(getattr(args, k))}
               for k in ("facts", "catalogue", "reconciliation", "user_confirmations")}
    manifest = {"schema": "document-ai-teacher-manifest.v1", "sources": sources, "summary": summaries,
                "outputs": {f: file_sha256(out / f) for f in ("catalogue.json", "examples.json")},
                "split_policy": "source+supplier/invoice+receipt connected components; sha256 fixed 70/15/15",
                "split_groups": {s: sorted({e["dependency_group"] for e in examples if e["split"] == s})
                                 for s in ("train", "validation", "test")},
                "new_data_policy": "evaluate_frozen_baseline_before_any_training; never_train_test_groups",
                "label_policy": "business_identity_not_printed_glyphs; proposals_not_human_gold",
                "production_ready": False}
    write_new(out / "manifest.json", manifest)
    print(json.dumps(summaries, ensure_ascii=True))


def load_frozen(folder):
    folder = Path(folder)
    manifest = load_json(folder / "manifest.json")
    for filename, digest in manifest["outputs"].items():
        if file_sha256(folder / filename) != digest:
            raise ValueError("Frozen input changed: " + filename)
    examples = load_json(folder / "examples.json")
    groups = manifest["split_groups"]
    sets = [set(groups[s]) for s in ("train", "validation", "test")]
    if any(sets[a] & sets[b] for a, b in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("Split group leakage")
    for e in examples:
        if e["dependency_group"] not in groups[e["split"]]:
            raise ValueError("Example split does not match frozen manifest")
    return manifest, load_json(folder / "catalogue.json"), examples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    for name in ("facts", "catalogue", "reconciliation", "user-confirmations", "out"):
        p.add_argument("--" + name, required=True)
    for name in ("baseline", "train", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--data", required=True)
        p.add_argument("--out", required=True)
        if name in ("train", "evaluate"):
            p.add_argument("--baseline", required=True)
        if name == "evaluate":
            p.add_argument("--model", required=True)
        if name == "train":
            p.add_argument("--epochs", type=int, default=20)
            p.add_argument("--checkpoints-dir", help="Fresh directory; defaults to <out>.checkpoints")
    args = parser.parse_args()
    if args.command == "prepare":
        return prepare(args)
    manifest, catalogue, examples = load_frozen(args.data)
    manifest_sha = file_sha256(Path(args.data) / "manifest.json")
    if args.command != "baseline":
        baseline = load_json(args.baseline)
        if baseline.get("manifest_sha256") != manifest_sha or baseline.get("kind") != "pretraining_baseline":
            raise ValueError("A baseline evaluated on this exact frozen manifest is required before training")
    if args.command == "train":
        require_hq()
        if not 1 <= args.epochs <= 100:
            raise ValueError("Epoch count must be between 1 and 100")
        if Path(args.out).exists():
            raise FileExistsError("Model output already exists; preserving previous run")
        metadata = {"manifest_sha256": manifest_sha, "baseline_sha256": file_sha256(args.baseline)}
        checkpoints_dir = args.checkpoints_dir or (str(args.out) + ".checkpoints")
        callback = checkpoint_writer(checkpoints_dir, metadata)
        model = fit_pairwise(catalogue, examples, epochs=args.epochs, checkpoint_callback=callback)
        model.update(**metadata)
        write_new(args.out, model)
        print(json.dumps({k: model[k] for k in ("actual_updates", "actual_pairs", "actual_examples", "epochs")}))
    else:
        model = load_json(args.model) if args.command == "evaluate" else None
        if model and model.get("manifest_sha256") != manifest_sha:
            raise ValueError("Model manifest mismatch")
        result = evaluate(ProductMatcher(catalogue, model), examples)
        result.update(manifest_sha256=manifest_sha,
                      kind="posttraining_evaluation" if model else "pretraining_baseline",
                      model_sha256=file_sha256(args.model) if model else None)
        write_new(args.out, result)
        print(json.dumps(result["split_metrics"]))


if __name__ == "__main__":
    main()
