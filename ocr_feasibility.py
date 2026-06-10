#!/usr/bin/env python
"""Raw-output-first OCR feasibility pipeline for Thai/English invoice PDFs."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ocr_environment import environment_config, load_dotenv, resolve_environment_name, validate_environment_path


MIN_PYTHON = (3, 10)


OPENAI_EXTRACTION_PROMPT = """You are a second-reader OCR engine for a feasibility study.

Rules:
- Extract EVERYTHING visible on this invoice page.
- Preserve observed text exactly as seen, including OCR-like mistakes, uncertain characters, broken words, punctuation, Thai text, English text, numbers, product codes, lot numbers, stamps, handwriting, and table text.
- Do not correct spelling.
- Do not normalize Thai or English text.
- Do not infer missing characters.
- Do not choose between conflicting readings.
- Mark uncertainty explicitly.
- If a character, word, row, or table cell is unclear, include it with an uncertainty note instead of dropping it.
- Return table structure only as observed. If row or cell boundaries are unclear, say so.

Return JSON with these keys:
{
  "raw_visible_text": ["line strings in reading order where possible"],
  "uncertain_text": [{"text": "...", "reason": "...", "location": "..."}],
  "tables": [{"title": null, "uncertain_structure": true/false, "rows": [["cell text as seen"]]}],
  "fields": [{"label_as_seen": "...", "value_as_seen": "...", "uncertain": true/false, "reason": "..."}],
  "marks_or_handwriting": [{"text_or_description": "...", "uncertain": true/false, "location": "..."}],
  "notes": ["visibility or extraction caveats"]
}
"""


@dataclass
class EngineStatus:
    engine: str
    available: bool
    status: str
    details: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="replace")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(make_json_safe(data), ensure_ascii=False, indent=2), encoding="utf-8")


def make_json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        preview = base64.b64encode(value[:256]).decode("ascii")
        return {
            "__type__": "bytes",
            "length": len(value),
            "sha1": hashlib.sha1(value).hexdigest(),
            "base64_preview_first_256_bytes": preview,
        }
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "tolist") and callable(getattr(value, "tolist")):
        try:
            return make_json_safe(value.tolist())
        except Exception:
            pass
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(v) for v in value]
    return value


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_markdown(path: Path, lines: Sequence[str]) -> None:
    write_text(path, "\n".join(lines).rstrip() + "\n")


def import_optional(module_name: str) -> Tuple[Any, Optional[str]]:
    try:
        return __import__(module_name, fromlist=["*"]), None
    except Exception as exc:
        return None, str(exc)


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def resolve_tesseract_command() -> Optional[str]:
    explicit = os.environ.get("TESSERACT_CMD")
    if explicit and Path(explicit).exists():
        return explicit
    discovered = shutil.which("tesseract")
    if discovered:
        return discovered
    if os.name == "nt":
        candidates = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
    return None


def run_command(args: Sequence[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    proc = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


def slug_for_pdf(path: Path) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("_") or "document"
    return f"{safe}_{digest}"


def discover_pdfs(input_path: Path) -> List[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.glob("*.pdf"))
    return []


def analyze_pdf(pdf_path: Path, output_dir: Path) -> Dict[str, Any]:
    fitz, fitz_err = import_optional("fitz")
    analysis: Dict[str, Any] = {
        "pdf": str(pdf_path.resolve()),
        "created_at": now_iso(),
        "tools": {},
        "pages": [],
        "classification": "unknown",
        "potential_challenges": [],
    }
    if fitz_err:
        analysis["tools"]["pymupdf"] = asdict(EngineStatus("pymupdf", False, "missing", fitz_err))
        write_json(output_dir / "analysis.json", analysis)
        return analysis

    doc = fitz.open(str(pdf_path))
    analysis["tools"]["pymupdf"] = asdict(EngineStatus("pymupdf", True, "ok"))
    analysis["page_count"] = doc.page_count
    analysis["metadata"] = dict(doc.metadata or {})

    text_pages = 0
    image_heavy_pages = 0
    for i, page in enumerate(doc):
        text = page.get_text("text") or ""
        images = page.get_images(full=True)
        drawings = page.get_drawings()
        page_info = {
            "page": i + 1,
            "width": page.rect.width,
            "height": page.rect.height,
            "rotation": page.rotation,
            "native_text_chars": len(text),
            "native_text_preview": text[:1000],
            "embedded_image_count": len(images),
            "drawing_count": len(drawings),
        }
        if len(text.strip()) > 50:
            text_pages += 1
        if images and len(text.strip()) < 50:
            image_heavy_pages += 1
        analysis["pages"].append(page_info)

    if text_pages == doc.page_count and doc.page_count:
        analysis["classification"] = "digitally_generated_or_text_layer_present"
    elif image_heavy_pages:
        analysis["classification"] = "scanned_or_image_dominant"
    elif text_pages:
        analysis["classification"] = "mixed_text_and_scanned"

    analysis["potential_challenges"] = [
        "Thai + English mixed content",
        "small invoice table text",
        "lot numbers and product codes",
        "numeric totals and discounts",
        "low contrast or faded photocopy text",
        "possible skewed scanned pages",
        "handwritten marks or signatures",
    ]
    write_json(output_dir / "analysis.json", analysis)
    doc.close()
    return analysis


def extract_native_text(pdf_path: Path, output_dir: Path) -> Dict[str, Any]:
    fitz, fitz_err = import_optional("fitz")
    native_dir = output_dir / "ocr" / "native"
    result = {"engine": "native_pdf_text", "pages": [], "status": "ok"}
    if fitz_err:
        result["status"] = "missing_dependency"
        result["error"] = fitz_err
        write_json(native_dir / "native.json", result)
        return result
    doc = fitz.open(str(pdf_path))
    for i, page in enumerate(doc):
        text = page.get_text("text") or ""
        rawdict = page.get_text("rawdict")
        page_id = f"page-{i + 1:04d}"
        write_text(native_dir / f"{page_id}.txt", text)
        write_json(native_dir / f"{page_id}.rawdict.json", rawdict)
        result["pages"].append({"page": i + 1, "text_path": f"{page_id}.txt", "chars": len(text)})
    doc.close()
    write_json(native_dir / "native.json", result)
    return result


def rasterize_pdf(pdf_path: Path, output_dir: Path, dpi: int) -> List[Path]:
    fitz, fitz_err = import_optional("fitz")
    if fitz_err:
        raise RuntimeError(f"PyMuPDF is required to rasterize PDFs: {fitz_err}")
    doc = fitz.open(str(pdf_path))
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    image_paths: List[Path] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        out = pages_dir / f"page-{i + 1:04d}.png"
        pix.save(str(out))
        image_paths.append(out)
    doc.close()
    return image_paths


def preprocess_page(image_path: Path, output_dir: Path) -> List[Path]:
    cv2, cv2_err = import_optional("cv2")
    if cv2_err:
        write_json(output_dir / "preprocess_status.json", {"status": "missing_dependency", "error": cv2_err})
        return [image_path]
    import numpy as np  # type: ignore

    page_name = image_path.stem
    pre_dir = output_dir / "preprocessed" / page_name
    pre_dir.mkdir(parents=True, exist_ok=True)
    image = cv2.imread(str(image_path))
    if image is None:
        write_json(pre_dir / "preprocess_status.json", {"status": "error", "error": "cv2.imread returned None"})
        return [image_path]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    variants: Dict[str, Any] = {"original": image}
    variants["gray"] = gray
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    variants["clahe"] = clahe.apply(gray)
    variants["denoised"] = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    _, variants["otsu"] = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants["adaptive_threshold"] = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 11
    )
    variants["sharpened"] = cv2.filter2D(gray, -1, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]]))
    variants["scaled_2x"] = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    # Deskew from foreground pixels, but keep the original even if the estimate is bad.
    coords = np.column_stack(np.where(variants["otsu"] < 255))
    if coords.size:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) <= 15:
            h, w = gray.shape[:2]
            center = (w // 2, h // 2)
            rot = cv2.getRotationMatrix2D(center, angle, 1.0)
            variants["deskewed"] = cv2.warpAffine(gray, rot, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    written = [image_path]
    metadata = []
    for name, variant in variants.items():
        out = pre_dir / f"{name}.png"
        cv2.imwrite(str(out), variant)
        written.append(out)
        metadata.append({"variant": name, "path": str(out), "reason": preprocessing_reason(name)})
    write_json(pre_dir / "variants.json", metadata)
    return written


def preprocessing_reason(name: str) -> str:
    reasons = {
        "original": "preserved untouched raster page",
        "gray": "reduces color noise while preserving text shape",
        "clahe": "raises local contrast for faint photocopy text",
        "denoised": "reduces scanner speckle and photocopy noise",
        "otsu": "global binarization for high contrast print",
        "adaptive_threshold": "local binarization for uneven lighting and faded regions",
        "sharpened": "emphasizes thin strokes and table text",
        "scaled_2x": "helps small numeric fields and lot numbers",
        "deskewed": "compensates for rotated scanned pages",
    }
    return reasons.get(name, "preprocessing variant")


def select_tesseract_variants(variants: List[Path], cpu_fast: bool) -> List[Path]:
    if not cpu_fast:
        return variants
    preferred = {"original", "clahe", "adaptive_threshold", "scaled_2x"}
    selected = [path for path in variants if path.stem in preferred]
    return selected or variants


def run_tesseract(image_variants_by_page: Dict[int, List[Path]], output_dir: Path, cpu_fast: bool = False) -> Dict[str, Any]:
    tess_dir = output_dir / "ocr" / "tesseract"
    psms = ["3", "6", "11"] if cpu_fast else ["3", "4", "6", "11", "12"]
    tesseract_cmd = resolve_tesseract_command()
    result: Dict[str, Any] = {
        "engine": "tesseract",
        "available": tesseract_cmd is not None,
        "command": tesseract_cmd,
        "cpu_fast": cpu_fast,
        "psm_attempts": psms,
        "pages": [],
    }
    if not result["available"]:
        result["status"] = "missing_executable"
        result["details"] = "tesseract is not available on PATH"
        write_json(tess_dir / "tesseract.json", result)
        return result
    for page, variants in image_variants_by_page.items():
        page_result = {"page": page, "variants": []}
        for image_path in select_tesseract_variants(variants, cpu_fast):
            variant_name = image_path.stem
            for psm in psms:
                out_base = tess_dir / f"page-{page:04d}_{variant_name}_psm-{psm}"
                cmd_common = [tesseract_cmd, str(image_path), str(out_base), "-l", "tha+eng", "--psm", psm, "tsv"]
                code, stdout, stderr = run_command(cmd_common)
                text_code, text_stdout, text_stderr = run_command(
                    [tesseract_cmd, str(image_path), "stdout", "-l", "tha+eng", "--psm", psm]
                )
                write_text(out_base.with_suffix(".stdout.txt"), text_stdout)
                write_text(out_base.with_suffix(".stderr.txt"), stderr + "\n" + text_stderr)
                page_result["variants"].append(
                    {
                        "variant": variant_name,
                        "psm": psm,
                        "image": str(image_path),
                        "returncode_tsv": code,
                        "returncode_text": text_code,
                        "text_path": str(out_base.with_suffix(".stdout.txt")),
                        "tsv_path": str(out_base.with_suffix(".tsv")),
                    }
                )
        result["pages"].append(page_result)
    result["status"] = "ok"
    write_json(tess_dir / "tesseract.json", result)
    return result


def run_easyocr(page_images: List[Path], output_dir: Path) -> Dict[str, Any]:
    easy_dir = output_dir / "ocr" / "easyocr"
    result: Dict[str, Any] = {"engine": "easyocr", "pages": []}
    easyocr, err = import_optional("easyocr")
    if err:
        result.update({"available": False, "status": "missing_dependency", "details": err})
        write_json(easy_dir / "easyocr.json", result)
        return result
    result["available"] = True
    try:
        reader = easyocr.Reader(["th", "en"], gpu=False)
        for idx, image_path in enumerate(page_images, 1):
            raw = reader.readtext(str(image_path), detail=1, paragraph=False)
            rows = []
            lines = []
            for item in raw:
                box, text, conf = item
                rows.append({"box": box, "text": text, "confidence": conf})
                lines.append(text)
            write_json(easy_dir / f"page-{idx:04d}.json", rows)
            write_text(easy_dir / f"page-{idx:04d}.txt", "\n".join(lines))
            result["pages"].append({"page": idx, "json_path": f"page-{idx:04d}.json", "items": len(rows)})
            result["current_page"] = idx
            write_json(easy_dir / "easyocr.json", result)
        result["status"] = "ok"
    except Exception as exc:
        result.update({"status": "error", "details": str(exc), "traceback": traceback.format_exc()})
    write_json(easy_dir / "easyocr.json", result)
    return result


def run_paddleocr(page_images: List[Path], output_dir: Path) -> Dict[str, Any]:
    paddle_dir = output_dir / "ocr" / "paddle"
    languages = ["th", "en"]
    result: Dict[str, Any] = {"engine": "paddleocr", "language_attempts": languages, "pages": []}
    paddleocr, err = import_optional("paddleocr")
    if err:
        result.update({"available": False, "status": "missing_dependency", "details": err})
        write_json(paddle_dir / "paddleocr.json", result)
        return result
    result["available"] = True
    try:
        for lang in languages:
            try:
                ocr = paddleocr.PaddleOCR(use_textline_orientation=True, lang=lang)
            except Exception as exc:
                result.setdefault("language_errors", []).append({"language": lang, "error": str(exc)})
                continue
            for idx, image_path in enumerate(page_images, 1):
                raw = list(ocr.predict(str(image_path)))
                rows = []
                lines = []
                for item in raw:
                    parsed_rows, parsed_lines = normalize_paddle_result(item, lang)
                    rows.extend(parsed_rows)
                    lines.extend(parsed_lines)
                write_json(paddle_dir / f"page-{idx:04d}_{lang}.json", rows)
                write_text(paddle_dir / f"page-{idx:04d}_{lang}.txt", "\n".join(lines))
                result["pages"].append(
                    {"page": idx, "language_attempt": lang, "json_path": f"page-{idx:04d}_{lang}.json", "items": len(rows)}
                )
                result["current_page"] = idx
                result["current_language_attempt"] = lang
                write_json(paddle_dir / "paddleocr.json", result)
        result["status"] = "ok"
        result["note"] = "Thai and English PaddleOCR passes are preserved separately; neither pass overwrites the other."
    except Exception as exc:
        result.update({"status": "error", "details": str(exc), "traceback": traceback.format_exc()})
    write_json(paddle_dir / "paddleocr.json", result)
    return result


def normalize_paddle_result(item: Any, lang: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    lines: List[str] = []
    if isinstance(item, dict):
        rec_texts = item.get("rec_texts") or []
        rec_scores = item.get("rec_scores") or []
        rec_polys = item.get("rec_polys") or item.get("dt_polys") or []
        for idx, text in enumerate(rec_texts):
            confidence = rec_scores[idx] if idx < len(rec_scores) else None
            box = rec_polys[idx] if idx < len(rec_polys) else None
            rows.append(
                {
                    "box": box,
                    "text": text,
                    "confidence": confidence,
                    "language_attempt": lang,
                }
            )
            if text is not None:
                lines.append(str(text))
        if rows:
            return rows, lines
    if isinstance(item, (list, tuple)):
        for sub in item:
            sub_rows, sub_lines = normalize_paddle_result(sub, lang)
            rows.extend(sub_rows)
            lines.extend(sub_lines)
    return rows, lines


def run_tables(pdf_path: Path, output_dir: Path) -> Dict[str, Any]:
    tables_dir = output_dir / "tables"
    result: Dict[str, Any] = {"engine": "camelot", "tables": []}
    camelot, err = import_optional("camelot")
    if err:
        result.update({"available": False, "status": "missing_dependency", "details": err})
        write_json(tables_dir / "tables.json", result)
        return result
    result["available"] = True
    try:
        for flavor in ("lattice", "stream"):
            try:
                tables = camelot.read_pdf(str(pdf_path), pages="all", flavor=flavor)
                for idx, table in enumerate(tables):
                    base = tables_dir / f"{flavor}_table-{idx + 1:04d}"
                    table.df.to_csv(str(base.with_suffix(".csv")), index=False)
                    result["tables"].append(
                        {
                            "flavor": flavor,
                            "index": idx + 1,
                            "shape": list(table.df.shape),
                            "accuracy": getattr(table, "accuracy", None),
                            "whitespace": getattr(table, "whitespace", None),
                            "csv_path": str(base.with_suffix(".csv")),
                        }
                    )
            except Exception as exc:
                result.setdefault("flavor_errors", []).append({"flavor": flavor, "error": str(exc)})
        result["status"] = "ok"
    except Exception as exc:
        result.update({"status": "error", "details": str(exc), "traceback": traceback.format_exc()})
    write_json(tables_dir / "tables.json", result)
    return result


def image_to_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def run_openai_second_reader(page_images: List[Path], output_dir: Path, model: str) -> Dict[str, Any]:
    openai_dir = output_dir / "ocr" / "openai"
    result: Dict[str, Any] = {"engine": "openai", "model": model, "pages": []}
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        result.update({"enabled": False, "status": "missing_api_key", "details": "OPENAI_API_KEY is not set"})
        write_json(openai_dir / "openai.json", result)
        return result
    openai, err = import_optional("openai")
    if err:
        result.update({"enabled": False, "status": "missing_dependency", "details": err})
        write_json(openai_dir / "openai.json", result)
        return result

    result["enabled"] = True
    try:
        client = openai.OpenAI(api_key=api_key)
        for idx, image_path in enumerate(page_images, 1):
            response = client.responses.create(
                model=model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": OPENAI_EXTRACTION_PROMPT},
                            {"type": "input_image", "image_url": image_to_data_url(image_path), "detail": "high"},
                        ],
                    }
                ],
            )
            raw_path = openai_dir / f"page-{idx:04d}.raw_response.json"
            parsed_path = openai_dir / f"page-{idx:04d}.parsed.json"
            text_path = openai_dir / f"page-{idx:04d}.txt"
            raw = response.model_dump() if hasattr(response, "model_dump") else response.to_dict_recursive()
            write_json(raw_path, raw)
            output_text = getattr(response, "output_text", "") or ""
            write_text(text_path, output_text)
            parsed: Any
            try:
                parsed = json.loads(output_text)
            except Exception:
                parsed = {"parse_status": "not_json", "raw_text": output_text}
            write_json(parsed_path, parsed)
            result["pages"].append(
                {
                    "page": idx,
                    "image": str(image_path),
                    "raw_response_path": str(raw_path),
                    "parsed_path": str(parsed_path),
                    "text_path": str(text_path),
                }
            )
        result["status"] = "ok"
    except Exception as exc:
        result.update({"status": "error", "details": str(exc), "traceback": traceback.format_exc()})
    write_json(openai_dir / "openai.json", result)
    return result


def best_tesseract_tsv_for_page(tess_dir: Path, page_number: int) -> Tuple[Optional[Path], Optional[float]]:
    best_path: Optional[Path] = None
    best_score: Optional[float] = None
    for tsv_path in sorted(tess_dir.glob(f"page-{page_number:04d}_*.tsv")):
        confidences: List[float] = []
        try:
            with tsv_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    text = normalize_text(row.get("text", ""))
                    conf_raw = row.get("conf", "")
                    if not text or not conf_raw or conf_raw == "-1":
                        continue
                    confidences.append(float(conf_raw))
        except Exception:
            continue
        if not confidences:
            continue
        score = sum(confidences) / len(confidences)
        if best_score is None or score > best_score:
            best_path = tsv_path
            best_score = score
    return best_path, best_score


def parse_tesseract_line_regions(output_dir: Path, page_number: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    tess_dir = output_dir / "ocr" / "tesseract"
    chosen_tsv, _ = best_tesseract_tsv_for_page(tess_dir, page_number)
    if not chosen_tsv:
        return [], None
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    with chosen_tsv.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            text = normalize_text(row.get("text", ""))
            conf_raw = row.get("conf", "")
            if not text or not conf_raw or conf_raw == "-1":
                continue
            try:
                conf = float(conf_raw)
                left = float(row["left"])
                top = float(row["top"])
                width = float(row["width"])
                height = float(row["height"])
            except Exception:
                continue
            key = (row.get("block_num", "0"), row.get("par_num", "0"), row.get("line_num", "0"))
            groups.setdefault(key, []).append(
                {"text": text, "confidence": conf, "bbox": [left, top, left + width, top + height]}
            )
    line_regions: List[Dict[str, Any]] = []
    for key, parts in groups.items():
        ordered = sorted(parts, key=lambda item: (item["bbox"][1], item["bbox"][0]))
        line_regions.append(
            {
                "engine": "tesseract",
                "bbox": union_box([item["bbox"] for item in ordered]),
                "text": " ".join(item["text"] for item in ordered),
                "confidence": sum(item["confidence"] for item in ordered) / len(ordered),
                "source": chosen_tsv.name,
                "line_key": {"block_num": key[0], "par_num": key[1], "line_num": key[2]},
            }
        )
    return line_regions, chosen_tsv.name


def parse_easyocr_regions(output_dir: Path, page_number: int) -> List[Dict[str, Any]]:
    easy_path = output_dir / "ocr" / "easyocr" / f"page-{page_number:04d}.json"
    rows = read_json(easy_path, [])
    regions: List[Dict[str, Any]] = []
    for row in rows:
        bbox = quad_to_bbox(row.get("box"))
        if not bbox:
            continue
        regions.append(
            {
                "engine": "easyocr",
                "bbox": bbox,
                "text": row.get("text", ""),
                "confidence": float(row.get("confidence") or 0.0),
                "source": easy_path.name,
            }
        )
    return regions


def parse_paddle_regions(output_dir: Path, page_number: int) -> List[Dict[str, Any]]:
    raw_regions: List[Dict[str, Any]] = []
    for lang in ("th", "en"):
        paddle_path = output_dir / "ocr" / "paddle" / f"page-{page_number:04d}_{lang}.json"
        rows = read_json(paddle_path, [])
        for row in rows:
            bbox = quad_to_bbox(row.get("box"))
            if not bbox:
                continue
            raw_regions.append(
                {
                    "engine": "paddle",
                    "bbox": bbox,
                    "text": row.get("text", ""),
                    "confidence": float(row.get("confidence") or 0.0),
                    "source": paddle_path.name,
                    "language_attempt": lang,
                }
            )
    merged: List[Dict[str, Any]] = []
    used = [False] * len(raw_regions)
    for index, item in enumerate(raw_regions):
        if used[index]:
            continue
        cluster = [item]
        used[index] = True
        changed = True
        while changed:
            changed = False
            for other_index, other in enumerate(raw_regions):
                if used[other_index]:
                    continue
                if any(boxes_close_enough(member["bbox"], other["bbox"]) for member in cluster):
                    cluster.append(other)
                    used[other_index] = True
                    changed = True
        best = max(cluster, key=lambda region: region.get("confidence", 0.0))
        merged.append(
            {
                "engine": "paddle",
                "bbox": union_box([member["bbox"] for member in cluster]),
                "text": best["text"],
                "confidence": best["confidence"],
                "source": "merged_paddle_th_en",
                "alternates": [
                    {
                        "language_attempt": member.get("language_attempt"),
                        "text": member.get("text", ""),
                        "confidence": member.get("confidence"),
                        "source": member.get("source"),
                    }
                    for member in cluster
                ],
            }
        )
    return merged


def cluster_spatial_regions(page_number: int, engine_regions: Dict[str, List[Dict[str, Any]]], output_dir: Path) -> List[Dict[str, Any]]:
    flat_regions: List[Dict[str, Any]] = []
    for engine_name, regions in engine_regions.items():
        for region in regions:
            entry = dict(region)
            entry["engine"] = engine_name
            entry["page"] = page_number
            flat_regions.append(entry)

    clusters: List[List[Dict[str, Any]]] = []
    for region in flat_regions:
        placed = False
        for cluster in clusters:
            if any(boxes_close_enough(region["bbox"], existing["bbox"]) for existing in cluster):
                cluster.append(region)
                placed = True
                break
        if not placed:
            clusters.append([region])

    changed = True
    while changed:
        changed = False
        merged_clusters: List[List[Dict[str, Any]]] = []
        while clusters:
            current = clusters.pop()
            remainder: List[List[Dict[str, Any]]] = []
            for other in clusters:
                if any(boxes_close_enough(a["bbox"], b["bbox"]) for a in current for b in other):
                    current.extend(other)
                    changed = True
                else:
                    remainder.append(other)
            clusters = remainder
            merged_clusters.append(current)
        clusters = merged_clusters

    page_width, page_height = page_dimensions(output_dir, page_number)
    fused_regions: List[Dict[str, Any]] = []
    for index, cluster in enumerate(clusters, 1):
        by_engine: Dict[str, List[Dict[str, Any]]] = {}
        for region in cluster:
            by_engine.setdefault(region["engine"], []).append(region)
        representative_by_engine = {
            engine_name: max(regions, key=lambda item: item.get("confidence", 0.0))
            for engine_name, regions in by_engine.items()
        }
        texts = {engine_name: representative_by_engine[engine_name]["text"] for engine_name in representative_by_engine}
        agreements: List[Tuple[str, str]] = []
        engines = sorted(texts)
        for left_index in range(len(engines)):
            for right_index in range(left_index + 1, len(engines)):
                left_engine = engines[left_index]
                right_engine = engines[right_index]
                if texts_agree(texts[left_engine], texts[right_engine]):
                    agreements.append((left_engine, right_engine))

        if len(engines) == 1:
            classification = "unique_to_one"
            normalized_candidate_text = normalize_text(next(iter(texts.values())))
            confidence_level = "low_to_medium"
        elif len(engines) == 3 and len(agreements) == 3:
            classification = "agreed_by_all"
            normalized_candidate_text = normalize_text(
                max(representative_by_engine.values(), key=lambda item: item.get("confidence", 0.0))["text"]
            )
            confidence_level = "high"
        elif agreements:
            classification = "agreed_by_two"
            agreeing_engines = agreements[0]
            pair_texts = [texts[agreeing_engines[0]], texts[agreeing_engines[1]]]
            normalized_candidate_text = normalize_text(max(pair_texts, key=len))
            confidence_level = "high"
        else:
            classification = "conflicting"
            normalized_candidate_text = None
            confidence_level = "conflict"

        fused_box = union_box([region["bbox"] for region in cluster])
        categories = sorted({category for text in texts.values() for category in classify_text_categories(text)})
        normalized_bbox = None
        if page_width and page_height:
            normalized_bbox = {
                "x1": round(fused_box[0] / page_width, 6),
                "y1": round(fused_box[1] / page_height, 6),
                "x2": round(fused_box[2] / page_width, 6),
                "y2": round(fused_box[3] / page_height, 6),
            }
        fused_regions.append(
            {
                "region_id": f"page-{page_number:04d}-region-{index:04d}",
                "page": page_number,
                "page_width": page_width,
                "page_height": page_height,
                "bbox": [round(value, 2) for value in fused_box],
                "normalized_bbox": normalized_bbox,
                "relative_y_band": page_y_band(fused_box, page_height),
                "source_engines_present": sorted(representative_by_engine),
                "raw_candidates": {
                    engine_name: {
                        "text": representative_by_engine[engine_name]["text"],
                        "confidence": representative_by_engine[engine_name].get("confidence"),
                        "source": representative_by_engine[engine_name].get("source"),
                    }
                    for engine_name in representative_by_engine
                },
                "classification": classification,
                "confidence_level": confidence_level,
                "normalized_candidate_text": normalized_candidate_text,
                "category_labels": categories,
                "spatial_member_count": len(cluster),
                "engine_pair_agreements": [
                    {"engines": [left, right], "text_similarity": round(text_similarity(texts[left], texts[right]), 4)}
                    for left, right in agreements
                ],
                "all_engine_observations": [
                    {
                        "engine": region["engine"],
                        "text": region.get("text", ""),
                        "confidence": region.get("confidence"),
                        "bbox": [round(value, 2) for value in region["bbox"]],
                        "source": region.get("source"),
                    }
                    for region in sorted(cluster, key=lambda item: (item["engine"], item["bbox"][1], item["bbox"][0]))
                ],
            }
        )
    return fused_regions


def fusion_regions_to_csv_rows(regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for region in regions:
        rows.append(
            {
                "region_id": region["region_id"],
                "page": region["page"],
                "classification": region["classification"],
                "confidence_level": region["confidence_level"],
                "relative_y_band": region["relative_y_band"],
                "bbox_x1": region["bbox"][0],
                "bbox_y1": region["bbox"][1],
                "bbox_x2": region["bbox"][2],
                "bbox_y2": region["bbox"][3],
                "source_engines_present": ",".join(region["source_engines_present"]),
                "normalized_candidate_text": region["normalized_candidate_text"] or "",
                "category_labels": ",".join(region["category_labels"]),
                "paddle_text": region["raw_candidates"].get("paddle", {}).get("text", ""),
                "paddle_confidence": region["raw_candidates"].get("paddle", {}).get("confidence", ""),
                "easyocr_text": region["raw_candidates"].get("easyocr", {}).get("text", ""),
                "easyocr_confidence": region["raw_candidates"].get("easyocr", {}).get("confidence", ""),
                "tesseract_text": region["raw_candidates"].get("tesseract", {}).get("text", ""),
                "tesseract_confidence": region["raw_candidates"].get("tesseract", {}).get("confidence", ""),
            }
        )
    return rows


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        headers = [
            "region_id",
            "page",
            "classification",
            "confidence_level",
            "relative_y_band",
            "bbox_x1",
            "bbox_y1",
            "bbox_x2",
            "bbox_y2",
            "source_engines_present",
            "normalized_candidate_text",
            "category_labels",
            "paddle_text",
            "paddle_confidence",
            "easyocr_text",
            "easyocr_confidence",
            "tesseract_text",
            "tesseract_confidence",
        ]
    else:
        headers = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_spatial_overlap_report(output_dir: Path, fusion_summary: Dict[str, Any]) -> None:
    lines = [
        "# Spatial OCR Overlap Report",
        "",
        f"Generated: {now_iso()}",
        "",
        "## Conclusion",
        "",
        "The current evidence shows that OCR fusion should precede table reconstruction.",
        "Most missing invoice information is not simply unstructured text from the same engines.",
        "Instead, the engines often either read different text from the same region or only one engine sees a region at all.",
        "",
        "## Per-Page Overlap Statistics",
        "",
    ]
    for page_entry in fusion_summary.get("pages", []):
        counts = page_entry.get("status_counts", {})
        lines.extend(
            [
                f"### Page {page_entry.get('page')}",
                "",
                f"- Fused regions: `{page_entry.get('fused_region_count', 0)}`",
                f"- `agreed_by_all`: `{counts.get('agreed_by_all', 0)}`",
                f"- `agreed_by_two`: `{counts.get('agreed_by_two', 0)}`",
                f"- `unique_to_one`: `{counts.get('unique_to_one', 0)}`",
                f"- `conflicting`: `{counts.get('conflicting', 0)}`",
                f"- Tesseract source TSV: `{page_entry.get('tesseract_source_tsv', 'none')}`",
                "",
            ]
        )
    lines.extend(["## By-Field-Category Statistics", ""])
    for category_name, counts in sorted(fusion_summary.get("categories", {}).items()):
        lines.extend(
            [
                f"### {category_name}",
                "",
                f"- Total regions: `{counts.get('total', 0)}`",
                f"- `agreed_by_all`: `{counts.get('agreed_by_all', 0)}`",
                f"- `agreed_by_two`: `{counts.get('agreed_by_two', 0)}`",
                f"- `unique_to_one`: `{counts.get('unique_to_one', 0)}`",
                f"- `conflicting`: `{counts.get('conflicting', 0)}`",
                "",
            ]
        )
    lines.extend(["## Same-Region Disagreement Examples", ""])
    examples = fusion_summary.get("conflict_examples", [])[:10]
    if not examples:
        lines.append("- No conflict examples available.")
    else:
        for example in examples:
            lines.extend(
                [
                    f"- Page {example.get('page')} [{example.get('region_id')}]: `{example.get('category_labels', [])}`",
                    f"  - Engines: `{example.get('source_engines_present', [])}`",
                ]
            )
            for engine_name, candidate in sorted(example.get("raw_candidates", {}).items()):
                lines.append(
                    f"  - {engine_name}: `{normalize_text(candidate.get('text', ''))}` (confidence `{candidate.get('confidence')}`)"
                )
    lines.extend(
        [
            "",
            "## Recovery Estimate",
            "",
            f"- Invoice-information regions analyzed: `{fusion_summary.get('focus_counts', {}).get('total', 0)}`",
            f"- Recoverable by structure alone estimate: `{fusion_summary.get('recovery_estimate', {}).get('recoverable_with_structure_only_estimate', 'n/a')}%`",
            f"- Still missing due to OCR disagreement estimate: `{fusion_summary.get('recovery_estimate', {}).get('still_missing_due_to_ocr_disagreement_estimate', 'n/a')}%`",
            "",
            "Table reconstruction will help later, but the measured bottleneck right now is disagreement and sparse overlap between engines at the same spatial regions.",
        ]
    )
    write_text(output_dir / "spatial_overlap_report.md", "\n".join(lines) + "\n")


def run_region_level_fusion(output_dir: Path) -> Dict[str, Any]:
    analysis = read_json(output_dir / "analysis.json", {})
    page_count = int(analysis.get("page_count") or 0)
    fusion_dir = output_dir / "fusion"
    fused_regions: List[Dict[str, Any]] = []
    per_page: List[Dict[str, Any]] = []
    category_names = [
        "thai_text",
        "english_text",
        "numeric_values",
        "dates",
        "tax_ids",
        "product_codes",
        "lot_numbers",
        "prices",
        "quantities",
    ]
    category_counts: Dict[str, Dict[str, int]] = {
        category: {"total": 0, "agreed_by_all": 0, "agreed_by_two": 0, "unique_to_one": 0, "conflicting": 0}
        for category in category_names
    }

    for page_number in range(1, page_count + 1):
        paddle_regions = parse_paddle_regions(output_dir, page_number)
        easyocr_regions = parse_easyocr_regions(output_dir, page_number)
        tesseract_regions, chosen_tsv = parse_tesseract_line_regions(output_dir, page_number)
        page_fused = cluster_spatial_regions(
            page_number,
            {"paddle": paddle_regions, "easyocr": easyocr_regions, "tesseract": tesseract_regions},
            output_dir,
        )
        for region in page_fused:
            for category in region.get("category_labels", []):
                if category in category_counts:
                    category_counts[category]["total"] += 1
                    category_counts[category][region["classification"]] += 1
        counts = {"agreed_by_all": 0, "agreed_by_two": 0, "unique_to_one": 0, "conflicting": 0}
        for region in page_fused:
            counts[region["classification"]] += 1
        per_page.append(
            {
                "page": page_number,
                "paddle_region_count": len(paddle_regions),
                "easyocr_region_count": len(easyocr_regions),
                "tesseract_region_count": len(tesseract_regions),
                "fused_region_count": len(page_fused),
                "tesseract_source_tsv": chosen_tsv,
                "status_counts": counts,
            }
        )
        fused_regions.extend(page_fused)

    unique_regions = [region for region in fused_regions if region["classification"] == "unique_to_one"]
    conflict_regions = [region for region in fused_regions if region["classification"] == "conflicting"]
    focus_categories = ["dates", "tax_ids", "product_codes", "lot_numbers", "prices", "quantities"]
    focus_counts = {"total": 0, "agreed_by_all": 0, "agreed_by_two": 0, "unique_to_one": 0, "conflicting": 0}
    for category in focus_categories:
        counts = category_counts[category]
        for key in focus_counts:
            focus_counts[key] += counts.get(key, 0)
    recoverable = focus_counts["agreed_by_all"] + focus_counts["agreed_by_two"]
    unresolved = focus_counts["unique_to_one"] + focus_counts["conflicting"]
    recovery_estimate = {
        "recoverable_with_structure_only_estimate": round((recoverable / focus_counts["total"]) * 100.0, 1)
        if focus_counts["total"]
        else None,
        "still_missing_due_to_ocr_disagreement_estimate": round((unresolved / focus_counts["total"]) * 100.0, 1)
        if focus_counts["total"]
        else None,
    }

    summary = {
        "created_at": now_iso(),
        "page_count": page_count,
        "pages": per_page,
        "categories": category_counts,
        "focus_counts": focus_counts,
        "recovery_estimate": recovery_estimate,
        "region_counts": {
            "total_fused_regions": len(fused_regions),
            "agreed_by_all": sum(1 for region in fused_regions if region["classification"] == "agreed_by_all"),
            "agreed_by_two": sum(1 for region in fused_regions if region["classification"] == "agreed_by_two"),
            "unique_to_one": len(unique_regions),
            "conflicting": len(conflict_regions),
        },
        "conflict_examples": conflict_regions[:15],
    }

    write_json(fusion_dir / "fused_regions.json", fused_regions)
    write_csv(fusion_dir / "fused_regions.csv", fusion_regions_to_csv_rows(fused_regions))
    write_json(fusion_dir / "conflicts.json", conflict_regions)
    write_json(fusion_dir / "unique_regions.json", unique_regions)
    write_json(fusion_dir / "fusion_summary.json", summary)
    build_spatial_overlap_report(output_dir, summary)

    summary_lines = [
        "# Fusion Summary",
        "",
        f"Generated: {now_iso()}",
        "",
        "## Region Counts",
        "",
        f"- Total fused regions: `{summary['region_counts']['total_fused_regions']}`",
        f"- `agreed_by_all`: `{summary['region_counts']['agreed_by_all']}`",
        f"- `agreed_by_two`: `{summary['region_counts']['agreed_by_two']}`",
        f"- `unique_to_one`: `{summary['region_counts']['unique_to_one']}`",
        f"- `conflicting`: `{summary['region_counts']['conflicting']}`",
        "",
        "## Confidence Rules Applied",
        "",
        "- 2+ engines that agree spatially and textually are preserved as high confidence.",
        "- Single-engine regions are preserved as low-to-medium confidence.",
        "- Same-region disagreements preserve all candidates and remain marked as conflicts.",
        "- No Thai spelling correction or numeric inference is applied.",
        "",
        "## Next-Step Readiness",
        "",
        "Each fused region preserves page number, fused box, normalized box coordinates, y-band, category labels, per-engine candidates, and confidence.",
        "That gives the next table-reconstruction step enough spatial evidence to map regions into header, customer, product-table, totals, and footer zones later without discarding today's disagreements.",
    ]
    write_text(fusion_dir / "fusion_summary.md", "\n".join(summary_lines) + "\n")
    return summary


ZONE_NAMES = [
    "header",
    "vendor_info",
    "customer_info",
    "invoice_metadata",
    "product_table_header",
    "product_table_body",
    "totals",
    "payment_info",
    "footer",
    "unknown",
]

ZONE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "header": (
        "original tax invoice",
        "ต้นฉบับใบกำกับภาษี",
        "tax invoice",
        "invoice",
        "zuellig",
        "pharma",
    ),
    "vendor_info": (
        "เลขประจำตัวผู้เสียภาษีอากร",
        "ผู้เสียภาษี",
        "บริษัท",
        "จำกัด",
        "โทร",
        "โทรศัพท์",
        "address",
        "ที่อยู่",
        "คลังสินค้า",
        "tax id",
        "vendor",
    ),
    "customer_info": (
        "bill to",
        "ship to",
        "ขายให้",
        "ส่งของที่",
        "customer",
        "cust. name",
        "cust. code",
        "ลูกค้า",
        "ผู้ซื้อ",
        "ผู้รับสินค้า",
    ),
    "invoice_metadata": (
        "inv#",
        "เลขที่",
        "วันที่",
        "date",
        "contract no",
        "reference",
        "po no",
        "payment term",
        "delivery route",
        "operator",
        "client",
        "page no",
        "reference po",
        "สัญญาเลขที่",
        "อ้างถึง",
        "ใบสั่งขาย",
        "กำหนดชำระ",
        "เลขที / inv#",
    ),
    "product_table_header": (
        "item code",
        "item description",
        "quantity",
        "quantit",
        "uom",
        "unit price",
        "amount (baht)",
        "รหัสสินค้า",
        "รายการสินค้า",
        "จำนวน",
        "หน่วย",
        "ราคาขายรวม",
        "ราคาขายไม่รวม",
        "จำนวนเงิน",
        "vat",
    ),
    "totals": (
        "total amount",
        "amount to be paid",
        "net before vat",
        "รวมทั้งสิ้น",
        "รวมเงิน",
        "ยอดจ่ายชำระ",
        "รวม",
        "subtotal",
        "net before",
    ),
    "payment_info": (
        "bank transfer",
        "bill payment",
        "mobile banking",
        "counter bank",
        "amount in cash",
        "cust. ref.",
        "bic code",
        "qr code",
        "line @",
        "line",
        "payment",
        "ชำระเงิน",
        "จ่ายบิล",
        "โอนเงิน",
        "สแกนจ่าย",
        "ธนาคาร",
        "เลขบัญชี",
    ),
    "footer": (
        "form no",
        "rev.no",
        "effective date",
        "page no",
        "reference :",
        "internal use only",
        "strictly confidential",
        "fm-ia-001",
        "sop-ia-001",
        "confidential",
    ),
}


def region_text_variants(region: Dict[str, Any]) -> List[str]:
    texts: List[str] = []
    normalized_candidate = normalize_text(region.get("normalized_candidate_text", ""))
    if normalized_candidate:
        texts.append(normalized_candidate)
    for candidate in region.get("raw_candidates", {}).values():
        text = normalize_text(candidate.get("text", ""))
        if text and text not in texts:
            texts.append(text)
    return texts


def zone_keyword_hits(texts: List[str], keywords: Tuple[str, ...]) -> List[str]:
    lowered_texts = [text.lower() for text in texts]
    hits: List[str] = []
    for keyword in keywords:
        keyword_lower = keyword.lower()
        if any(keyword_lower in text for text in lowered_texts):
            hits.append(keyword)
    return hits


def normalized_box(region: Dict[str, Any]) -> Dict[str, float]:
    box = region.get("normalized_bbox")
    if box:
        return {
            "x1": float(box.get("x1", 0.0)),
            "y1": float(box.get("y1", 0.0)),
            "x2": float(box.get("x2", 0.0)),
            "y2": float(box.get("y2", 0.0)),
        }
    page_width = float(region.get("page_width") or 1.0)
    page_height = float(region.get("page_height") or 1.0)
    bbox = region.get("bbox", [0.0, 0.0, 0.0, 0.0])
    return {
        "x1": float(bbox[0]) / page_width,
        "y1": float(bbox[1]) / page_height,
        "x2": float(bbox[2]) / page_width,
        "y2": float(bbox[3]) / page_height,
    }


def first_candidate_y(regions: List[Dict[str, Any]], default: float) -> float:
    ys = [normalized_box(region)["y1"] for region in regions]
    return min(ys) if ys else default


def build_page_zone_context(page_regions: List[Dict[str, Any]]) -> Dict[str, float]:
    table_header_candidates: List[Dict[str, Any]] = []
    totals_candidates: List[Dict[str, Any]] = []
    payment_candidates: List[Dict[str, Any]] = []
    footer_candidates: List[Dict[str, Any]] = []

    for region in page_regions:
        texts = region_text_variants(region)
        box = normalized_box(region)
        width = box["x2"] - box["x1"]
        if zone_keyword_hits(texts, ZONE_KEYWORDS["product_table_header"]) and width >= 0.25:
            table_header_candidates.append(region)
        if zone_keyword_hits(texts, ZONE_KEYWORDS["totals"]):
            totals_candidates.append(region)
        if zone_keyword_hits(texts, ZONE_KEYWORDS["payment_info"]):
            payment_candidates.append(region)
        if zone_keyword_hits(texts, ZONE_KEYWORDS["footer"]):
            footer_candidates.append(region)

    product_header_y = first_candidate_y(table_header_candidates, 0.24)
    product_header_bottom = max(
        [normalized_box(region)["y2"] for region in table_header_candidates],
        default=min(product_header_y + 0.05, 0.34),
    )
    totals_start = first_candidate_y(
        [
            region
            for region in totals_candidates
            if normalized_box(region)["y1"] >= product_header_bottom
        ],
        0.60,
    )
    payment_start = first_candidate_y(
        [
            region
            for region in payment_candidates
            if normalized_box(region)["y1"] >= max(product_header_bottom, totals_start - 0.02)
        ],
        0.74,
    )
    footer_start = first_candidate_y(
        [
            region
            for region in footer_candidates
            if normalized_box(region)["y1"] >= max(product_header_bottom, totals_start - 0.02)
        ],
        0.88,
    )
    product_body_end = min([boundary for boundary in [totals_start, payment_start, footer_start] if boundary > product_header_bottom], default=0.88)
    if product_body_end <= product_header_bottom:
        product_body_end = min(product_header_bottom + 0.35, 0.88)
    return {
        "product_header_y": product_header_y,
        "product_header_bottom": product_header_bottom,
        "totals_start": max(totals_start, product_header_bottom),
        "payment_start": max(payment_start, product_header_bottom),
        "footer_start": max(footer_start, product_header_bottom),
        "product_body_start": product_header_bottom,
        "product_body_end": product_body_end,
    }


def score_region_zone(region: Dict[str, Any], context: Dict[str, float]) -> Dict[str, Any]:
    box = normalized_box(region)
    x1 = box["x1"]
    x2 = box["x2"]
    y1 = box["y1"]
    y2 = box["y2"]
    width = x2 - x1
    center_x = (x1 + x2) / 2.0
    texts = region_text_variants(region)
    categories = set(region.get("category_labels", []))
    classification = region.get("classification", "")

    scores = {zone: 0.0 for zone in ZONE_NAMES}
    reasons: Dict[str, List[str]] = {zone: [] for zone in ZONE_NAMES}

    def add(zone: str, points: float, reason: str) -> None:
        scores[zone] += points
        reasons[zone].append(reason)

    header_hits = zone_keyword_hits(texts, ZONE_KEYWORDS["header"])
    vendor_hits = zone_keyword_hits(texts, ZONE_KEYWORDS["vendor_info"])
    customer_hits = zone_keyword_hits(texts, ZONE_KEYWORDS["customer_info"])
    metadata_hits = zone_keyword_hits(texts, ZONE_KEYWORDS["invoice_metadata"])
    table_header_hits = zone_keyword_hits(texts, ZONE_KEYWORDS["product_table_header"])
    totals_hits = zone_keyword_hits(texts, ZONE_KEYWORDS["totals"])
    payment_hits = zone_keyword_hits(texts, ZONE_KEYWORDS["payment_info"])
    footer_hits = zone_keyword_hits(texts, ZONE_KEYWORDS["footer"])

    if y1 <= 0.12:
        add("header", 2.0, "top 12% of page")
    if header_hits:
        add("header", 4.0 + len(header_hits) * 0.5, f"header keywords: {', '.join(header_hits[:4])}")

    if vendor_hits:
        add("vendor_info", 4.0 + len(vendor_hits) * 0.5, f"vendor keywords: {', '.join(vendor_hits[:4])}")
    if "tax_ids" in categories:
        add("vendor_info", 2.0, "tax id category")
    if y1 < context["product_header_y"] + 0.08 and x1 < 0.62:
        add("vendor_info", 1.0, "upper-left before table")

    if customer_hits:
        add("customer_info", 4.0 + len(customer_hits) * 0.5, f"customer keywords: {', '.join(customer_hits[:4])}")
    if y1 < context["product_header_y"] + 0.10 and 0.02 < center_x < 0.72:
        add("customer_info", 1.0, "customer block position")

    if metadata_hits:
        add("invoice_metadata", 4.0 + len(metadata_hits) * 0.5, f"metadata keywords: {', '.join(metadata_hits[:4])}")
    if y1 < context["product_header_y"] + 0.10 and center_x >= 0.45:
        add("invoice_metadata", 1.0, "upper-right metadata position")
    if "dates" in categories and y1 < context["product_header_y"] + 0.12:
        add("invoice_metadata", 1.0, "top-area date")

    if table_header_hits and y1 <= context["product_header_bottom"] + 0.03:
        add("product_table_header", 5.0 + len(table_header_hits) * 0.5, f"table-header keywords: {', '.join(table_header_hits[:4])}")
    if abs(y1 - context["product_header_y"]) <= 0.04:
        add("product_table_header", 2.0, "near table header row")
    if width >= 0.45 and y1 <= context["product_header_bottom"] + 0.02:
        add("product_table_header", 1.0, "wide row near header")

    if y1 >= context["product_body_start"] and y2 <= context["product_body_end"]:
        add("product_table_body", 3.0, "between table header and totals/payment")
    if categories & {"product_codes", "lot_numbers", "prices", "quantities", "dates", "numeric_values"}:
        add("product_table_body", 2.0, "product-like categories")
    if classification in {"agreed_by_two", "conflicting"} and y1 >= context["product_body_start"] and y2 <= context["product_body_end"]:
        add("product_table_body", 0.5, "structured table-like disagreement")

    if totals_hits and y1 >= context["product_header_bottom"] - 0.02:
        add("totals", 5.0 + len(totals_hits) * 0.5, f"totals keywords: {', '.join(totals_hits[:4])}")
    if y1 >= context["totals_start"] and y1 < context["payment_start"] + 0.02:
        add("totals", 2.0, "totals vertical band")
    if categories & {"prices", "numeric_values"} and x1 >= 0.55 and y1 >= context["totals_start"] - 0.04:
        add("totals", 1.0, "right-side numeric totals pattern")

    if payment_hits and y1 >= context["product_header_bottom"] - 0.02:
        add("payment_info", 5.0 + len(payment_hits) * 0.5, f"payment keywords: {', '.join(payment_hits[:4])}")
    if y1 >= context["payment_start"] and y1 < context["footer_start"] + 0.02:
        add("payment_info", 2.0, "payment vertical band")
    if region.get("relative_y_band") == "bottom":
        add("payment_info", 1.0, "bottom-page instruction area")

    if footer_hits:
        add("footer", 5.0 + len(footer_hits) * 0.5, f"footer keywords: {', '.join(footer_hits[:4])}")
    if y1 >= context["footer_start"]:
        add("footer", 2.0, "footer vertical band")
    if "strictly confidential" in " ".join(text.lower() for text in texts):
        add("footer", 2.0, "document footer marker")

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_zone, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_score < 2.5:
        best_zone = "unknown"
    margin = best_score - second_score
    if best_zone == "unknown" or best_score < 3.0 or margin < 1.0:
        zone_confidence = "low"
    elif best_score >= 5.0 and margin >= 2.0:
        zone_confidence = "high"
    else:
        zone_confidence = "medium"

    return {
        "zone": best_zone,
        "zone_confidence": zone_confidence,
        "zone_reasons": reasons.get(best_zone, [])[:5],
        "zone_score": round(best_score, 2),
        "zone_score_margin": round(margin, 2),
        "zone_rankings": [
            {"zone": zone_name, "score": round(score, 2)}
            for zone_name, score in ranked[:4]
            if score > 0
        ],
    }


def zoned_regions_to_csv_rows(regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for region in regions:
        rows.append(
            {
                "region_id": region["region_id"],
                "page": region["page"],
                "zone": region.get("zone", "unknown"),
                "zone_confidence": region.get("zone_confidence", ""),
                "classification": region["classification"],
                "relative_y_band": region["relative_y_band"],
                "bbox_x1": region["bbox"][0],
                "bbox_y1": region["bbox"][1],
                "bbox_x2": region["bbox"][2],
                "bbox_y2": region["bbox"][3],
                "normalized_candidate_text": region.get("normalized_candidate_text") or "",
                "category_labels": ",".join(region.get("category_labels", [])),
                "source_engines_present": ",".join(region.get("source_engines_present", [])),
                "zone_reasons": " | ".join(region.get("zone_reasons", [])),
            }
        )
    return rows


def build_zone_summary(output_dir: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Zone Summary",
        "",
        f"Generated: {now_iso()}",
        "",
        "## Region Counts By Zone",
        "",
    ]
    for zone_name in ZONE_NAMES:
        zone_count = summary.get("zone_counts", {}).get(zone_name, 0)
        lines.append(f"- `{zone_name}`: `{zone_count}`")
    lines.extend(["", "## Page Zone Counts", ""])
    for page_entry in summary.get("pages", []):
        lines.append(f"### Page {page_entry['page']}")
        lines.append("")
        for zone_name in ZONE_NAMES:
            lines.append(f"- `{zone_name}`: `{page_entry['zone_counts'].get(zone_name, 0)}`")
        lines.append("")
    lines.extend(["## Uncertain Zone Examples", ""])
    uncertain = summary.get("uncertain_examples", [])
    if not uncertain:
        lines.append("- No uncertain zone examples.")
    else:
        for example in uncertain[:10]:
            lines.append(
                f"- [{example['region_id']}] page {example['page']} -> `{example['zone']}` "
                f"(confidence `{example['zone_confidence']}`, reasons: `{'; '.join(example.get('zone_reasons', []))}`)"
            )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "Zones are heuristic and are intended to prepare fused OCR evidence for the next scanned table-reconstruction step.",
            "No OCR text was changed and no table structure was inferred here.",
        ]
    )
    write_text(output_dir / "fusion" / "zone_summary.md", "\n".join(lines) + "\n")


def run_region_zoning(output_dir: Path) -> Dict[str, Any]:
    fusion_dir = output_dir / "fusion"
    fused_regions = read_json(fusion_dir / "fused_regions.json", [])
    if not fused_regions:
        summary = {"status": "missing_fused_regions", "created_at": now_iso(), "zone_counts": {zone: 0 for zone in ZONE_NAMES}}
        write_json(fusion_dir / "zoned_regions.json", [])
        write_csv(fusion_dir / "zoned_regions.csv", [])
        write_json(fusion_dir / "zone_summary.json", summary)
        build_zone_summary(output_dir, summary)
        return summary

    regions_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for region in fused_regions:
        regions_by_page.setdefault(int(region.get("page", 0)), []).append(region)

    zoned_regions: List[Dict[str, Any]] = []
    page_summaries: List[Dict[str, Any]] = []
    zone_counts = {zone: 0 for zone in ZONE_NAMES}

    for page_number in sorted(regions_by_page):
        page_regions = sorted(regions_by_page[page_number], key=lambda item: (normalized_box(item)["y1"], normalized_box(item)["x1"]))
        context = build_page_zone_context(page_regions)
        page_zone_counts = {zone: 0 for zone in ZONE_NAMES}
        for region in page_regions:
            zone_info = score_region_zone(region, context)
            zoned = {**region, **zone_info}
            zoned_regions.append(zoned)
            page_zone_counts[zoned["zone"]] += 1
            zone_counts[zoned["zone"]] += 1
        page_summaries.append({"page": page_number, "zone_counts": page_zone_counts, "context": context})

    uncertain_examples = [
        region
        for region in zoned_regions
        if region.get("zone") == "unknown" or region.get("zone_confidence") == "low"
    ]
    summary = {
        "created_at": now_iso(),
        "status": "ok",
        "total_regions": len(zoned_regions),
        "zone_counts": zone_counts,
        "pages": page_summaries,
        "uncertain_examples": uncertain_examples[:20],
    }
    write_json(fusion_dir / "zoned_regions.json", zoned_regions)
    write_csv(fusion_dir / "zoned_regions.csv", zoned_regions_to_csv_rows(zoned_regions))
    write_json(fusion_dir / "zone_summary.json", summary)
    build_zone_summary(output_dir, summary)
    return summary


def is_numeric_dominant_text(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    return bool(re.fullmatch(r"[\d\s,./:%()-]+", normalized))


def is_noise_like_region(region: Dict[str, Any]) -> bool:
    text = normalize_text(region.get("normalized_candidate_text") or "")
    if not text:
        return True
    if len(text) <= 2:
        return True
    alnum_count = sum(ch.isalnum() for ch in text)
    punctuation_count = sum(ch in "{}[]|~`^_*" for ch in text)
    weird_ratio = punctuation_count / max(len(text), 1)
    if weird_ratio > 0.18:
        return True
    if alnum_count == 0:
        return True
    if text.lower() in {"i.", "if", "ay", "a.", "ef", "fu", "th"}:
        return True
    return False


def region_center(region: Dict[str, Any]) -> Tuple[float, float]:
    box = normalized_box(region)
    return ((box["x1"] + box["x2"]) / 2.0, (box["y1"] + box["y2"]) / 2.0)


def overlap_in_y(region_a: Dict[str, Any], region_b: Dict[str, Any], tolerance: float = 0.01) -> bool:
    a = normalized_box(region_a)
    b = normalized_box(region_b)
    return min(a["y2"], b["y2"]) - max(a["y1"], b["y1"]) >= -tolerance


def nearest_zone_anchor(
    region: Dict[str, Any],
    anchors_by_zone: Dict[str, List[Dict[str, Any]]],
    max_distance: float = 0.18,
) -> Optional[Tuple[str, Dict[str, Any], float]]:
    cx, cy = region_center(region)
    best: Optional[Tuple[str, Dict[str, Any], float]] = None
    for zone_name, anchors in anchors_by_zone.items():
        for anchor in anchors:
            ax, ay = region_center(anchor)
            distance = math.dist((cx, cy), (ax, ay))
            if distance <= max_distance and (best is None or distance < best[2]):
                best = (zone_name, anchor, distance)
    return best


def build_zone_anchor_context(page_regions: List[Dict[str, Any]], context: Dict[str, float]) -> Dict[str, Any]:
    anchors_by_zone: Dict[str, List[Dict[str, Any]]] = {zone: [] for zone in ZONE_NAMES if zone != "unknown"}
    table_columns: List[float] = []
    totals_x_positions: List[float] = []
    payment_y_positions: List[float] = []

    for region in page_regions:
        zone = region.get("zone")
        confidence = region.get("zone_confidence")
        if zone in anchors_by_zone and confidence in {"high", "medium"}:
            anchors_by_zone[zone].append(region)
        if zone in {"product_table_header", "product_table_body"} and confidence in {"high", "medium"}:
            table_columns.append(normalized_box(region)["x1"])
        if zone == "totals" and confidence in {"high", "medium"}:
            totals_x_positions.append(normalized_box(region)["x1"])
        if zone == "payment_info" and confidence in {"high", "medium"}:
            payment_y_positions.append(normalized_box(region)["y1"])

    header_bottom = max(
        [normalized_box(region)["y2"] for region in anchors_by_zone["product_table_header"]],
        default=context["product_header_bottom"],
    )
    metadata_right_band = min(
        [normalized_box(region)["x1"] for region in anchors_by_zone["invoice_metadata"]],
        default=0.62,
    )
    customer_band_bottom = max(
        [normalized_box(region)["y2"] for region in anchors_by_zone["customer_info"]],
        default=min(context["product_header_y"], 0.26),
    )
    return {
        "anchors_by_zone": anchors_by_zone,
        "table_column_xs": sorted(table_columns),
        "totals_x_positions": sorted(totals_x_positions),
        "payment_y_positions": sorted(payment_y_positions),
        "header_bottom": header_bottom,
        "metadata_right_band": metadata_right_band,
        "customer_band_bottom": customer_band_bottom,
    }


def infer_unknown_bucket(region: Dict[str, Any], anchor_context: Dict[str, Any], context: Dict[str, float]) -> Dict[str, str]:
    text = normalize_text(region.get("normalized_candidate_text") or "")
    categories = set(region.get("category_labels", []))
    box = normalized_box(region)
    x1 = box["x1"]
    y1 = box["y1"]

    if is_noise_like_region(region):
        return {"why_unknown": "OCR noise / unreadable", "suggested_zone": ""}
    if is_numeric_dominant_text(text):
        if y1 <= anchor_context["header_bottom"] + 0.02 and x1 >= anchor_context["metadata_right_band"] - 0.08:
            return {"why_unknown": "valid numeric field", "suggested_zone": "invoice_metadata"}
        if y1 >= context["totals_start"] - 0.04 and x1 >= 0.62:
            return {"why_unknown": "valid numeric field", "suggested_zone": "totals"}
        if context["product_body_start"] <= y1 <= context["product_body_end"]:
            return {"why_unknown": "valid numeric field", "suggested_zone": "product_table_body"}
        return {"why_unknown": "valid numeric field", "suggested_zone": ""}
    if y1 <= anchor_context["header_bottom"] + 0.02 and x1 >= anchor_context["metadata_right_band"] - 0.1:
        return {"why_unknown": "likely invoice metadata", "suggested_zone": "invoice_metadata"}
    if y1 <= anchor_context["customer_band_bottom"] + 0.03 and x1 < 0.7:
        return {"why_unknown": "likely customer/vendor info", "suggested_zone": "customer_info"}
    if context["product_body_start"] <= y1 <= context["product_body_end"] and categories & {"product_codes", "prices", "quantities", "lot_numbers", "numeric_values"}:
        return {"why_unknown": "likely product table content", "suggested_zone": "product_table_body"}
    if y1 >= context["totals_start"] - 0.03:
        return {"why_unknown": "likely totals/payment/footer", "suggested_zone": "payment_info" if y1 >= context["payment_start"] - 0.02 else "totals"}
    return {"why_unknown": "ambiguous due to poor OCR", "suggested_zone": ""}


def refine_region_zone_v2(
    region: Dict[str, Any],
    context: Dict[str, float],
    anchor_context: Dict[str, Any],
    page_regions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    region = dict(region)
    box = normalized_box(region)
    x1 = box["x1"]
    y1 = box["y1"]
    y2 = box["y2"]
    width = box["x2"] - box["x1"]
    text = normalize_text(region.get("normalized_candidate_text") or "")
    categories = set(region.get("category_labels", []))
    zone = region.get("zone", "unknown")
    zone_confidence = region.get("zone_confidence", "low")
    zone_reasons = list(region.get("zone_reasons", []))

    def adopt(new_zone: str, confidence: str, reason: str) -> None:
        nonlocal zone, zone_confidence, zone_reasons
        zone = new_zone
        zone_confidence = confidence
        zone_reasons = zone_reasons + [reason]

    nearest = nearest_zone_anchor(region, anchor_context["anchors_by_zone"], max_distance=0.14)
    table_columns = anchor_context["table_column_xs"]
    near_table_column = any(abs(x1 - column_x) <= 0.04 for column_x in table_columns[:12])
    row_peer_zones = [
        peer.get("zone")
        for peer in page_regions
        if peer.get("region_id") != region.get("region_id")
        and overlap_in_y(region, peer, tolerance=0.012)
        and peer.get("zone") != "unknown"
    ]

    if zone == "unknown":
        if text and y1 <= anchor_context["header_bottom"] + 0.025 and x1 >= anchor_context["metadata_right_band"] - 0.08:
            if "dates" in categories or is_numeric_dominant_text(text):
                adopt("invoice_metadata", "medium", "top-right numeric/date field near metadata anchors")
        if zone == "unknown" and nearest and nearest[0] in {"invoice_metadata", "customer_info", "vendor_info"}:
            if nearest[2] <= 0.08 and y1 <= anchor_context["customer_band_bottom"] + 0.05:
                adopt(nearest[0], "medium", f"nearby {nearest[0]} anchor")
        if zone == "unknown" and context["product_body_start"] - 0.01 <= y1 <= context["product_body_end"] + 0.01:
            if near_table_column or "product_table_header" in row_peer_zones or "product_table_body" in row_peer_zones:
                if categories & {"product_codes", "prices", "quantities", "lot_numbers", "numeric_values", "english_text", "thai_text"}:
                    adopt("product_table_body", "medium", "inside table band with aligned table neighbors")
        if zone == "unknown" and y1 <= context["product_header_bottom"] + 0.025:
            if width >= 0.08 and (near_table_column or "product_table_header" in row_peer_zones):
                adopt("product_table_header", "medium", "aligned with repeated table-header row")
        if zone == "unknown" and y1 >= context["totals_start"] - 0.03 and x1 >= 0.58:
            if categories & {"prices", "numeric_values"}:
                adopt("totals", "medium", "right-aligned numeric field near totals band")
        if zone == "unknown" and y1 >= context["payment_start"] - 0.02:
            if nearest and nearest[0] == "payment_info":
                adopt("payment_info", "medium", "near payment instruction block")
            elif region.get("relative_y_band") == "bottom" and (categories & {"numeric_values", "english_text", "thai_text"}):
                adopt("payment_info", "low", "bottom-page payment-like content")
        if zone == "unknown" and y1 >= context["footer_start"] - 0.01:
            if nearest and nearest[0] == "footer":
                adopt("footer", "medium", "near footer anchor")

    if zone == "invoice_metadata" and zone_confidence == "low" and y1 <= anchor_context["header_bottom"] + 0.03:
        zone_confidence = "medium"
        zone_reasons.append("metadata confidence raised by top-right placement")
    if zone == "product_table_body" and zone_confidence == "medium" and (near_table_column or "product_table_body" in row_peer_zones):
        zone_confidence = "high"
        zone_reasons.append("table-body confidence raised by column/row alignment")
    if zone == "payment_info" and "amount in cash" in text.lower():
        zone_confidence = "high"

    why_unknown = ""
    suggested_zone = ""
    if zone == "unknown":
        diagnosis = infer_unknown_bucket(region, anchor_context, context)
        why_unknown = diagnosis["why_unknown"]
        suggested_zone = diagnosis["suggested_zone"]

    region["zone"] = zone
    region["zone_confidence"] = zone_confidence
    region["zone_reasons"] = zone_reasons[:6]
    region["why_unknown"] = why_unknown
    region["suggested_zone"] = suggested_zone
    return region


def zoned_regions_v2_to_csv_rows(regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for region in regions:
        rows.append(
            {
                "region_id": region["region_id"],
                "page": region["page"],
                "zone": region.get("zone", "unknown"),
                "zone_confidence": region.get("zone_confidence", ""),
                "classification": region["classification"],
                "relative_y_band": region["relative_y_band"],
                "bbox_x1": region["bbox"][0],
                "bbox_y1": region["bbox"][1],
                "bbox_x2": region["bbox"][2],
                "bbox_y2": region["bbox"][3],
                "normalized_candidate_text": region.get("normalized_candidate_text") or "",
                "category_labels": ",".join(region.get("category_labels", [])),
                "source_engines_present": ",".join(region.get("source_engines_present", [])),
                "zone_reasons": " | ".join(region.get("zone_reasons", [])),
                "why_unknown": region.get("why_unknown", ""),
                "suggested_zone": region.get("suggested_zone", ""),
            }
        )
    return rows


def build_zone_summary_v2(output_dir: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Zone Summary V2",
        "",
        f"Generated: {now_iso()}",
        "",
        f"- Old unknown count: `{summary.get('old_unknown_count', 0)}`",
        f"- New unknown count: `{summary.get('new_unknown_count', 0)}`",
        f"- Unknown reduction: `{summary.get('unknown_reduction_pct', 0.0)}%`",
        "",
        "## Counts By Zone",
        "",
    ]
    before = summary.get("previous_zone_counts", {})
    after = summary.get("zone_counts", {})
    for zone_name in ZONE_NAMES:
        lines.append(f"- `{zone_name}`: `{before.get(zone_name, 0)}` -> `{after.get(zone_name, 0)}`")
    lines.extend(["", "## Improved Examples", ""])
    for example in summary.get("improved_examples", [])[:12]:
        lines.append(
            f"- [{example['region_id']}] page {example['page']}: `{example['previous_zone']}` -> `{example['zone']}` "
            f"({example['zone_confidence']}) because `{'; '.join(example.get('zone_reasons', []))}`"
        )
    lines.extend(["", "## Still Unknown Examples", ""])
    for example in summary.get("still_unknown_examples", [])[:12]:
        lines.append(
            f"- [{example['region_id']}] page {example['page']}: `{example.get('why_unknown', '')}`"
            + (f" suggested `{example.get('suggested_zone')}`" if example.get("suggested_zone") else "")
        )
    write_text(output_dir / "fusion" / "zone_summary_v2.md", "\n".join(lines) + "\n")


def build_unknown_analysis(output_dir: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Unknown Region Analysis",
        "",
        f"Generated: {now_iso()}",
        "",
        f"- Unknown regions after v2: `{summary.get('new_unknown_count', 0)}`",
        "",
        "## Buckets",
        "",
    ]
    for bucket_name, bucket in summary.get("unknown_buckets", {}).items():
        lines.append(f"### {bucket_name}")
        lines.append("")
        lines.append(f"- Count: `{bucket.get('count', 0)}`")
        if bucket.get("examples"):
            for example in bucket["examples"][:8]:
                lines.append(
                    f"- [{example['region_id']}] page {example['page']}: `{example.get('normalized_candidate_text') or ''}`"
                    + (f" suggested `{example.get('suggested_zone')}`" if example.get("suggested_zone") else "")
                )
        lines.append("")
    write_text(output_dir / "fusion" / "unknown_analysis.md", "\n".join(lines) + "\n")


def run_region_zoning_v2(output_dir: Path) -> Dict[str, Any]:
    fusion_dir = output_dir / "fusion"
    fused_regions = read_json(fusion_dir / "fused_regions.json", [])
    previous_regions = read_json(fusion_dir / "zoned_regions.json", [])
    previous_by_id = {region.get("region_id"): region for region in previous_regions if region.get("region_id")}
    previous_zone_counts = {zone: 0 for zone in ZONE_NAMES}
    for region in previous_regions:
        previous_zone_counts[region.get("zone", "unknown")] += 1

    if not fused_regions:
        summary = {
            "status": "missing_fused_regions",
            "created_at": now_iso(),
            "zone_counts": {zone: 0 for zone in ZONE_NAMES},
            "previous_zone_counts": previous_zone_counts,
            "old_unknown_count": previous_zone_counts.get("unknown", 0),
            "new_unknown_count": 0,
            "unknown_reduction_pct": 0.0,
        }
        write_json(fusion_dir / "zoned_regions_v2.json", [])
        write_csv(fusion_dir / "zoned_regions_v2.csv", [])
        write_json(fusion_dir / "zone_summary_v2.json", summary)
        build_zone_summary_v2(output_dir, summary)
        build_unknown_analysis(output_dir, summary)
        return summary

    regions_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for region in fused_regions:
        regions_by_page.setdefault(int(region.get("page", 0)), []).append(region)

    zoned_regions_v2: List[Dict[str, Any]] = []
    zone_counts = {zone: 0 for zone in ZONE_NAMES}
    improved_examples: List[Dict[str, Any]] = []

    for page_number in sorted(regions_by_page):
        page_regions_base = sorted(regions_by_page[page_number], key=lambda item: (normalized_box(item)["y1"], normalized_box(item)["x1"]))
        page_context = build_page_zone_context(page_regions_base)
        prelim_regions = [{**region, **score_region_zone(region, page_context)} for region in page_regions_base]
        anchor_context = build_zone_anchor_context(prelim_regions, page_context)
        refined_page_regions: List[Dict[str, Any]] = []
        for region in prelim_regions:
            refined = refine_region_zone_v2(region, page_context, anchor_context, prelim_regions)
            refined_page_regions.append(refined)
            zone_counts[refined.get("zone", "unknown")] += 1
            previous_zone = previous_by_id.get(refined["region_id"], {}).get("zone", "unknown")
            if previous_zone == "unknown" and refined.get("zone") != "unknown":
                improved_examples.append(
                    {
                        "region_id": refined["region_id"],
                        "page": refined["page"],
                        "previous_zone": previous_zone,
                        "zone": refined["zone"],
                        "zone_confidence": refined.get("zone_confidence"),
                        "zone_reasons": refined.get("zone_reasons", []),
                    }
                )
        zoned_regions_v2.extend(refined_page_regions)

    new_unknown = [region for region in zoned_regions_v2 if region.get("zone") == "unknown"]
    old_unknown_count = previous_zone_counts.get("unknown", 0)
    new_unknown_count = len(new_unknown)
    reduction_pct = round(((old_unknown_count - new_unknown_count) / old_unknown_count) * 100.0, 1) if old_unknown_count else 0.0

    unknown_buckets_template = {
        "OCR noise / unreadable": [],
        "valid text but missing keyword rules": [],
        "valid numeric field": [],
        "likely invoice metadata": [],
        "likely customer/vendor info": [],
        "likely product table content": [],
        "likely totals/payment/footer": [],
        "ambiguous due to poor OCR": [],
    }
    unknown_buckets = {name: [] for name in unknown_buckets_template}
    for region in new_unknown:
        bucket = region.get("why_unknown") or "ambiguous due to poor OCR"
        if bucket not in unknown_buckets:
            bucket = "ambiguous due to poor OCR"
        unknown_buckets[bucket].append(region)

    summary = {
        "created_at": now_iso(),
        "status": "ok",
        "zone_counts": zone_counts,
        "previous_zone_counts": previous_zone_counts,
        "old_unknown_count": old_unknown_count,
        "new_unknown_count": new_unknown_count,
        "unknown_reduction_pct": reduction_pct,
        "improved_examples": improved_examples[:30],
        "still_unknown_examples": new_unknown[:30],
        "unknown_buckets": {
            name: {
                "count": len(regions),
                "examples": [
                    {
                        "region_id": region["region_id"],
                        "page": region["page"],
                        "normalized_candidate_text": region.get("normalized_candidate_text"),
                        "suggested_zone": region.get("suggested_zone", ""),
                    }
                    for region in regions[:8]
                ],
            }
            for name, regions in unknown_buckets.items()
        },
    }

    write_json(fusion_dir / "zoned_regions_v2.json", zoned_regions_v2)
    write_csv(fusion_dir / "zoned_regions_v2.csv", zoned_regions_v2_to_csv_rows(zoned_regions_v2))
    write_json(fusion_dir / "zone_summary_v2.json", summary)
    build_zone_summary_v2(output_dir, summary)
    build_unknown_analysis(output_dir, summary)
    return summary


def tokenize(text: str) -> List[str]:
    return re.findall(r"[\w\u0E00-\u0E7F.%-]+", text, flags=re.UNICODE)


THAI_RE = re.compile(r"[\u0E00-\u0E7F]")
ENGLISH_RE = re.compile(r"[A-Za-z]")
NUMERIC_RE = re.compile(r"\d")
DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
TAX_ID_RE = re.compile(r"(?<!\d)\d{13}(?!\d)")
PRICE_RE = re.compile(r"(?<!\d)\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)|(?<!\d)\d+\.\d{2}(?!\d)")
LOT_RE = re.compile(r"\b(?:LOT[:\s-]*)?[A-Z]{1,4}\d{3,}\b", flags=re.IGNORECASE)
PRODUCT_CODE_RE = re.compile(r"\b(?:[A-Z]{2,}[A-Z0-9-]{2,}|\d{4,8})\b")
QUANTITY_RE = re.compile(r"(?<!\d)\d{1,3}(?![\d.])")
MOJIBAKE_HINTS = ("เธ", "เน", "โ€", "฿")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def canonical_text(text: str) -> str:
    return re.sub(r"[^\w\u0E00-\u0E7F]+", "", normalize_text(text).lower(), flags=re.UNICODE)


def text_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    aa = canonical_text(a)
    bb = canonical_text(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    return SequenceMatcher(None, aa, bb).ratio()


def texts_agree(a: str, b: str) -> bool:
    aa = canonical_text(a)
    bb = canonical_text(b)
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    if aa.isdigit() or bb.isdigit():
        return aa == bb
    return text_similarity(a, b) >= 0.82


def quad_to_bbox(quad: Any) -> Optional[List[float]]:
    if not quad:
        return None
    try:
        xs = [float(point[0]) for point in quad]
        ys = [float(point[1]) for point in quad]
    except Exception:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def box_area(box: Sequence[float]) -> float:
    return max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1]))


def union_box(boxes: Sequence[Sequence[float]]) -> List[float]:
    return [
        min(float(box[0]) for box in boxes),
        min(float(box[1]) for box in boxes),
        max(float(box[2]) for box in boxes),
        max(float(box[3]) for box in boxes),
    ]


def box_intersection(a: Sequence[float], b: Sequence[float]) -> float:
    x1 = max(float(a[0]), float(b[0]))
    y1 = max(float(a[1]), float(b[1]))
    x2 = min(float(a[2]), float(b[2]))
    y2 = min(float(a[3]), float(b[3]))
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1)


def overlap_score(a: Sequence[float], b: Sequence[float]) -> float:
    inter = box_intersection(a, b)
    if inter <= 0:
        return 0.0
    smallest = min(box_area(a), box_area(b))
    return inter / smallest if smallest else 0.0


def y_overlap_ratio(a: Sequence[float], b: Sequence[float]) -> float:
    inter = max(0.0, min(float(a[3]), float(b[3])) - max(float(a[1]), float(b[1])))
    denom = min(float(a[3]) - float(a[1]), float(b[3]) - float(b[1]))
    return inter / denom if denom else 0.0


def boxes_close_enough(a: Sequence[float], b: Sequence[float]) -> bool:
    if overlap_score(a, b) >= 0.35:
        return True
    center_ax = (float(a[0]) + float(a[2])) / 2.0
    center_bx = (float(b[0]) + float(b[2])) / 2.0
    center_ay = (float(a[1]) + float(a[3])) / 2.0
    center_by = (float(b[1]) + float(b[3])) / 2.0
    width = max(float(a[2]) - float(a[0]), float(b[2]) - float(b[0]))
    height = max(1.0, min(float(a[3]) - float(a[1]), float(b[3]) - float(b[1])))
    return (
        y_overlap_ratio(a, b) >= 0.55
        and abs(center_ax - center_bx) <= max(40.0, 0.6 * width)
        and abs(center_ay - center_by) <= max(25.0, 0.75 * height)
    )


def classify_text_categories(text: str) -> List[str]:
    categories: List[str] = []
    if THAI_RE.search(text) or any(marker in text for marker in MOJIBAKE_HINTS):
        categories.append("thai_text")
    if ENGLISH_RE.search(text):
        categories.append("english_text")
    if NUMERIC_RE.search(text):
        categories.append("numeric_values")
    if DATE_RE.search(text):
        categories.append("dates")
    if TAX_ID_RE.search(text):
        categories.append("tax_ids")
    if PRODUCT_CODE_RE.search(text) and len(canonical_text(text)) >= 4:
        categories.append("product_codes")
    if LOT_RE.search(text):
        categories.append("lot_numbers")
    if PRICE_RE.search(text):
        categories.append("prices")
    if QUANTITY_RE.fullmatch(normalize_text(text)):
        try:
            quantity = int(normalize_text(text))
        except ValueError:
            quantity = 0
        if 0 < quantity <= 999:
            categories.append("quantities")
    return categories


def page_dimensions(output_dir: Path, page_number: int) -> Tuple[Optional[int], Optional[int]]:
    image_path = output_dir / "pages" / f"page-{page_number:04d}.png"
    cv2, err = import_optional("cv2")
    if err or not image_path.exists():
        return None, None
    image = cv2.imread(str(image_path))
    if image is None:
        return None, None
    height, width = image.shape[:2]
    return int(width), int(height)


def page_y_band(box: Sequence[float], page_height: Optional[int]) -> str:
    if not page_height:
        return "unknown"
    center_y = (float(box[1]) + float(box[3])) / 2.0
    ratio = center_y / float(page_height)
    if ratio < 0.2:
        return "top"
    if ratio < 0.4:
        return "upper_middle"
    if ratio < 0.7:
        return "middle"
    if ratio < 0.88:
        return "lower_middle"
    return "bottom"


def collect_text_files(root: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not root.exists():
        return data
    for path in sorted(root.rglob("*.txt")):
        if path.name.endswith(".stderr.txt"):
            continue
        try:
            data[str(path.relative_to(root))] = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return data


def classify_disagreements(oss_text: str, openai_text: str) -> Dict[str, Any]:
    oss_tokens = set(tokenize(oss_text))
    openai_tokens = set(tokenize(openai_text))
    common = oss_tokens & openai_tokens
    oss_only = sorted(oss_tokens - openai_tokens)
    openai_only = sorted(openai_tokens - oss_tokens)
    status = "all_agree"
    if oss_only and openai_only:
        status = "conflict"
    elif oss_only:
        status = "oss_only"
    elif openai_only:
        status = "openai_only"
    elif common and len(common) < max(len(oss_tokens), len(openai_tokens)):
        status = "partial_overlap"
    return {
        "status": status,
        "oss_token_count": len(oss_tokens),
        "openai_token_count": len(openai_tokens),
        "common_token_count": len(common),
        "oss_only_sample": oss_only[:200],
        "openai_only_sample": openai_only[:200],
    }


def compare_outputs(output_dir: Path) -> Dict[str, Any]:
    comparison_dir = output_dir / "comparison"
    oss_roots = {
        "native": output_dir / "ocr" / "native",
        "tesseract": output_dir / "ocr" / "tesseract",
        "paddle": output_dir / "ocr" / "paddle",
        "easyocr": output_dir / "ocr" / "easyocr",
    }
    openai_texts = collect_text_files(output_dir / "ocr" / "openai")
    oss_text_by_engine = {engine: "\n".join(collect_text_files(path).values()) for engine, path in oss_roots.items()}
    all_oss = "\n".join(oss_text_by_engine.values())
    all_openai = "\n".join(openai_texts.values())
    summary = {
        "created_at": now_iso(),
        "engine_token_counts": {engine: len(tokenize(text)) for engine, text in oss_text_by_engine.items()},
        "openai_token_count": len(tokenize(all_openai)),
        "openai_vs_all_oss": classify_disagreements(all_oss, all_openai) if all_openai else {"status": "openai_not_run"},
        "openai_vs_engine": {},
    }
    for engine, text in oss_text_by_engine.items():
        summary["openai_vs_engine"][engine] = (
            classify_disagreements(text, all_openai) if all_openai else {"status": "openai_not_run"}
        )
    write_json(comparison_dir / "comparison.json", summary)
    return summary


def confidence_summary(output_dir: Path) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    tess_dir = output_dir / "ocr" / "tesseract"
    confidences: List[float] = []
    for tsv in tess_dir.glob("*.tsv"):
        try:
            with tsv.open("r", encoding="utf-8", errors="replace", newline="") as fh:
                for row in csv.DictReader(fh, delimiter="\t"):
                    conf = row.get("conf", "")
                    if conf and conf != "-1":
                        confidences.append(float(conf))
        except Exception:
            pass
    if confidences:
        summary["tesseract"] = {
            "count": len(confidences),
            "min": min(confidences),
            "max": max(confidences),
            "avg": sum(confidences) / len(confidences),
        }
    return summary


def generate_report(output_dir: Path, pdf_path: Path, statuses: Dict[str, Any], comparison: Dict[str, Any]) -> None:
    analysis = read_json(output_dir / "analysis.json", {})
    conf = confidence_summary(output_dir)
    openai_status = statuses.get("openai", {})
    fusion_summary = read_json(output_dir / "fusion" / "fusion_summary.json", {})
    lines = [
        f"# OCR Feasibility Report: {pdf_path.name}",
        "",
        f"Generated: {now_iso()}",
        "",
        "## Document Analysis",
        "",
        f"- Classification: `{analysis.get('classification', 'unknown')}`",
        f"- Pages: `{analysis.get('page_count', 'unknown')}`",
        f"- Potential challenges: {', '.join(analysis.get('potential_challenges', []))}",
        "",
        "## Engine Status",
        "",
    ]
    for name, status in statuses.items():
        lines.append(f"- {name}: `{status.get('status', 'unknown')}`")
    lines.extend(["", "## Confidence", ""])
    if conf:
        lines.append(f"- Tesseract confidence: `{conf.get('tesseract')}`")
    else:
        lines.append("- No engine confidence values available.")
    lines.extend(["", "## OpenAI Second Reader", ""])
    if openai_status.get("status") == "ok":
        lines.append("- OpenAI ran after OSS outputs were written.")
        lines.append("- Raw OpenAI responses are saved separately in `ocr/openai/`.")
    else:
        lines.append(f"- OpenAI did not produce second-reader output: `{openai_status.get('status', 'not_enabled')}`.")
    lines.extend(
        [
            "",
            "## Disagreement Summary",
            "",
            f"- OpenAI vs all OSS: `{comparison.get('openai_vs_all_oss', {}).get('status', 'openai_not_run')}`",
            f"- Engine token counts: `{comparison.get('engine_token_counts', {})}`",
            f"- OpenAI token count: `{comparison.get('openai_token_count', 0)}`",
            "",
            "## Region-Level Fusion",
            "",
            f"- Total fused regions: `{fusion_summary.get('region_counts', {}).get('total_fused_regions', 'not_run')}`",
            f"- Agreed by all: `{fusion_summary.get('region_counts', {}).get('agreed_by_all', 'not_run')}`",
            f"- Agreed by two: `{fusion_summary.get('region_counts', {}).get('agreed_by_two', 'not_run')}`",
            f"- Unique to one: `{fusion_summary.get('region_counts', {}).get('unique_to_one', 'not_run')}`",
            f"- Conflicting: `{fusion_summary.get('region_counts', {}).get('conflicting', 'not_run')}`",
            f"- Spatial overlap audit: `spatial_overlap_report.md`",
            "",
            "## Required Evaluation Questions",
            "",
            f"- Recall improved by OpenAI: `{improvement_label(comparison, 'recall')}`",
            f"- Table structure improved by OpenAI: `requires manual review of tables and ocr/openai parsed output`",
            f"- Numeric fields improved by OpenAI: `requires manual review of disagreement samples`",
            f"- Lot numbers improved by OpenAI: `requires manual review of disagreement samples`",
            f"- Thai text improved by OpenAI: `requires manual review of disagreement samples`",
            f"- English text improved by OpenAI: `requires manual review of disagreement samples`",
            f"- Low-contrast/faded text improved by OpenAI: `requires visual review against page images`",
            "",
            "## Non-Correction Guarantee",
            "",
            "This pipeline preserves raw OCR outputs independently. It does not use OpenAI or any other engine to correct, normalize, infer, overwrite, or silently resolve another engine's output.",
        ]
    )
    write_text(output_dir / "report.md", "\n".join(lines) + "\n")


def improvement_label(comparison: Dict[str, Any], metric: str) -> str:
    if comparison.get("openai_vs_all_oss", {}).get("status") == "openai_not_run":
        return "not evaluated; OpenAI not run"
    openai_only = comparison.get("openai_vs_all_oss", {}).get("openai_only_sample", [])
    return "possible; OpenAI-only tokens present" if openai_only else "no obvious token-level improvement"


def process_pdf(pdf_path: Path, out_root: Path, dpi: int, use_openai: bool, openai_model: str, cpu_fast: bool) -> Path:
    run_dir = out_root / slug_for_pdf(pdf_path)
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "run_manifest.json",
        {"pdf": str(pdf_path.resolve()), "started_at": now_iso(), "dpi": dpi, "cpu_fast": cpu_fast},
    )

    statuses: Dict[str, Any] = {}
    statuses["analysis"] = {"status": "ok"}
    analyze_pdf(pdf_path, run_dir)
    statuses["native"] = extract_native_text(pdf_path, run_dir)
    page_images = rasterize_pdf(pdf_path, run_dir, dpi)

    variants_by_page: Dict[int, List[Path]] = {}
    for idx, image_path in enumerate(page_images, 1):
        variants_by_page[idx] = preprocess_page(image_path, run_dir)

    statuses["tesseract"] = run_tesseract(variants_by_page, run_dir, cpu_fast=cpu_fast)
    statuses["paddle"] = run_paddleocr(page_images, run_dir)
    statuses["easyocr"] = run_easyocr(page_images, run_dir)
    statuses["tables"] = run_tables(pdf_path, run_dir)

    oss_complete_marker = run_dir / "ocr" / "oss_complete.json"
    write_json(oss_complete_marker, {"completed_at": now_iso(), "engines": ["native", "tesseract", "paddle", "easyocr", "tables"]})

    if use_openai:
        statuses["openai"] = run_openai_second_reader(page_images, run_dir, openai_model)
    else:
        statuses["openai"] = {"status": "disabled", "details": "Run with --openai to enable optional second reader."}
        write_json(run_dir / "ocr" / "openai" / "openai.json", statuses["openai"])

    write_json(run_dir / "engine_status.json", statuses)
    statuses["fusion"] = run_region_level_fusion(run_dir)
    statuses["zoning"] = run_region_zoning(run_dir)
    statuses["zoning_v2"] = run_region_zoning_v2(run_dir)
    write_json(run_dir / "engine_status.json", statuses)
    comparison = compare_outputs(run_dir)
    generate_report(run_dir, pdf_path, statuses, comparison)
    return run_dir


def run_fusion_only_on_existing_run(run_dir: Path) -> Dict[str, Any]:
    summary = run_region_level_fusion(run_dir)
    zoning_summary = run_region_zoning(run_dir)
    zoning_v2_summary = run_region_zoning_v2(run_dir)
    engine_status = read_json(run_dir / "engine_status.json", {})
    engine_status["fusion"] = summary
    engine_status["zoning"] = zoning_summary
    engine_status["zoning_v2"] = zoning_v2_summary
    write_json(run_dir / "engine_status.json", engine_status)
    pdf_path = Path(read_json(run_dir / "run_manifest.json", {}).get("pdf", run_dir.name))
    comparison = compare_outputs(run_dir)
    generate_report(run_dir, pdf_path, engine_status, comparison)
    return summary


def run_zoning_only_on_existing_run(run_dir: Path) -> Dict[str, Any]:
    summary = run_region_zoning(run_dir)
    summary_v2 = run_region_zoning_v2(run_dir)
    engine_status = read_json(run_dir / "engine_status.json", {})
    engine_status["zoning"] = summary
    engine_status["zoning_v2"] = summary_v2
    write_json(run_dir / "engine_status.json", engine_status)
    return summary_v2


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    index = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def cluster_adjacent_values(values: Sequence[Tuple[int, int, int]], gap_tolerance: int = 2) -> List[Dict[str, int]]:
    if not values:
        return []
    clusters: List[Dict[str, int]] = []
    start = values[0][0]
    prev = values[0][0]
    bucket = [values[0]]
    for position, total_dark, longest_run in values[1:]:
        if position <= prev + gap_tolerance:
            prev = position
            bucket.append((position, total_dark, longest_run))
            continue
        best = max(bucket, key=lambda item: (item[2], item[1]))
        clusters.append(
            {
                "start": start,
                "end": prev,
                "best_position": best[0],
                "best_total_dark": best[1],
                "best_longest_run": best[2],
            }
        )
        start = position
        prev = position
        bucket = [(position, total_dark, longest_run)]
    best = max(bucket, key=lambda item: (item[2], item[1]))
    clusters.append(
        {
            "start": start,
            "end": prev,
            "best_position": best[0],
            "best_total_dark": best[1],
            "best_longest_run": best[2],
        }
    )
    return clusters


def longest_binary_run(values: Sequence[int]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value:
            current += 1
            if current > longest:
                longest = current
        else:
            current = 0
    return longest


def detect_strong_horizontal_lines(binary_image: Any) -> List[Dict[str, int]]:
    height, width = binary_image.shape
    candidates: List[Tuple[int, int, int]] = []
    min_longest_run = max(120, int(width * 0.22))
    min_dark_total = max(120, int(width * 0.22))
    for y in range(height):
        row = binary_image[y, :]
        total_dark = int(row.sum())
        longest_run = longest_binary_run(row)
        if longest_run >= min_longest_run and total_dark >= min_dark_total:
            candidates.append((y, total_dark, longest_run))
    return cluster_adjacent_values(candidates, gap_tolerance=2)


def detect_strong_vertical_lines(binary_image: Any, top_y: int, bottom_y: int) -> List[Dict[str, int]]:
    crop = binary_image[top_y:bottom_y, :]
    crop_height = crop.shape[0]
    candidates: List[Tuple[int, int, int]] = []
    min_longest_run = max(140, int(crop_height * 0.17))
    min_dark_total = max(140, int(crop_height * 0.18))
    for x in range(crop.shape[1]):
        column = crop[:, x]
        total_dark = int(column.sum())
        longest_run = longest_binary_run(column)
        if longest_run >= min_longest_run and total_dark >= min_dark_total:
            candidates.append((x, total_dark, longest_run))
    return cluster_adjacent_values(candidates, gap_tolerance=2)


def choose_nearest_cluster(
    clusters: Sequence[Dict[str, int]],
    target: float,
    max_distance: float,
) -> Optional[Dict[str, int]]:
    if not clusters:
        return None
    best: Optional[Dict[str, int]] = None
    best_distance = None
    for cluster in clusters:
        distance = abs(cluster["best_position"] - target)
        if distance <= max_distance and (best_distance is None or distance < best_distance):
            best = cluster
            best_distance = distance
    return best


def pick_main_product_gap(body_regions: Sequence[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int]]:
    if len(body_regions) < 2:
        return None, None
    ordered = sorted(body_regions, key=lambda region: (region["bbox"][1], region["bbox"][3]))
    best_gap = 0.0
    best_index = None
    for index in range(len(ordered) - 1):
        gap = float(ordered[index + 1]["bbox"][1]) - float(ordered[index]["bbox"][1])
        if gap > best_gap:
            best_gap = gap
            best_index = index
    if best_index is None or best_gap < 180.0:
        return None, None
    return int(round(ordered[best_index]["bbox"][3])), int(round(ordered[best_index + 1]["bbox"][1]))


def build_table_band_validation_image(
    image_path: Path,
    output_path: Path,
    band: Dict[str, Any],
) -> None:
    pil_image, pil_err = import_optional("PIL.Image")
    draw_module, draw_err = import_optional("PIL.ImageDraw")
    if pil_err or draw_err:
        return
    image = pil_image.open(str(image_path)).convert("RGBA")
    overlay = pil_image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = draw_module.Draw(overlay)
    x1, y1, x2, y2 = [int(value) for value in band["bbox"]]
    draw.rectangle((x1, y1, x2, y2), outline=(31, 111, 235, 255), width=6, fill=(31, 111, 235, 38))
    header_bottom = int(band.get("header_separator_y") or y1)
    draw.line((x1, header_bottom, x2, header_bottom), fill=(29, 78, 216, 255), width=4)
    label = f"TABLE BAND POC | {band['confidence']} | {band['confidence_score']}"
    draw.rectangle((x1 + 10, max(10, y1 + 10), min(x1 + 560, image.size[0] - 10), max(10, y1 + 44)), fill=(15, 23, 42, 210))
    draw.text((x1 + 18, max(16, y1 + 16)), label, fill=(255, 255, 255, 255))
    merged = pil_image.alpha_composite(image, overlay).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.save(str(output_path))


def run_table_band_detection_poc(run_dir: Path, page_number: int = 3) -> Dict[str, Any]:
    fusion_dir = run_dir / "fusion"
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    zoned_regions = read_json(fusion_dir / "zoned_regions_v2.json", [])
    page_image_path = run_dir / "pages" / f"page-{page_number:04d}.png"
    summary_path = tables_dir / "table_band_summary.md"
    output_path = tables_dir / "table_bands.json"
    validation_image_path = tables_dir / f"table_band_page-{page_number:04d}_validation.png"

    summary_lines = [
        "# Table Band Summary",
        "",
        f"Generated: {now_iso()}",
        "",
        "- Scope: `Layer A only`",
        f"- Page: `{page_number}`",
        "- Mode: `staging table-band detection proof of concept`",
        "",
    ]

    if not zoned_regions:
        payload = {
            "created_at": now_iso(),
            "status": "missing_zoned_regions_v2",
            "page": page_number,
            "bands": [],
        }
        write_json(output_path, payload)
        summary_lines.extend(["No `zoned_regions_v2.json` data was available.", ""])
        write_markdown(summary_path, summary_lines)
        return payload

    if not page_image_path.exists():
        payload = {
            "created_at": now_iso(),
            "status": "missing_page_image",
            "page": page_number,
            "bands": [],
        }
        write_json(output_path, payload)
        summary_lines.extend([f"Missing page image: `{page_image_path}`", ""])
        write_markdown(summary_path, summary_lines)
        return payload

    page_regions = [region for region in zoned_regions if int(region.get("page", 0)) == page_number]
    product_regions = [
        region
        for region in page_regions
        if region.get("zone") in {"product_table_header", "product_table_body"}
    ]
    if not product_regions:
        payload = {
            "created_at": now_iso(),
            "status": "no_product_table_regions",
            "page": page_number,
            "bands": [],
        }
        write_json(output_path, payload)
        summary_lines.extend(["No page-3 product-table zones were available for detection.", ""])
        write_markdown(summary_path, summary_lines)
        return payload

    pil_image, pil_err = import_optional("PIL.Image")
    numpy_module, np_err = import_optional("numpy")
    if pil_err or np_err:
        payload = {
            "created_at": now_iso(),
            "status": "missing_image_dependencies",
            "page": page_number,
            "bands": [],
            "details": {"pillow": pil_err, "numpy": np_err},
        }
        write_json(output_path, payload)
        summary_lines.extend(
            [
                "Image-based table-band validation could not run because Pillow or NumPy is missing.",
                "",
                f"- Pillow: `{pil_err or 'ok'}`",
                f"- NumPy: `{np_err or 'ok'}`",
            ]
        )
        write_markdown(summary_path, summary_lines)
        return payload

    image = numpy_module.array(pil_image.open(str(page_image_path)).convert("L"))
    image_height, image_width = image.shape
    binary_image = (image < 180).astype("uint8")

    image_space_regions = [
        region
        for region in product_regions
        if float(region["bbox"][2]) <= image_width * 1.02
    ]
    header_regions = [region for region in image_space_regions if region.get("zone") == "product_table_header"]
    body_regions = [region for region in image_space_regions if region.get("zone") == "product_table_body"]
    nonempty_product_regions = [
        region for region in image_space_regions if normalize_text(region.get("normalized_candidate_text") or "")
    ]

    body_min_y = min((float(region["bbox"][1]) for region in body_regions), default=0.0)
    prelim_top = min(
        (
            float(region["bbox"][1])
            for region in header_regions
            if float(region["bbox"][1]) >= body_min_y - 180.0
        ),
        default=min(float(region["bbox"][1]) for region in image_space_regions),
    )
    prelim_left = min(float(region["bbox"][0]) for region in nonempty_product_regions) if nonempty_product_regions else 0.0
    prelim_right = max(
        float(region["bbox"][2])
        for region in image_space_regions
        if float(region["bbox"][2]) <= image_width
    )

    main_body_end, post_gap_start = pick_main_product_gap(body_regions)
    totals_candidates = [
        float(region["bbox"][1])
        for region in page_regions
        if region.get("zone") in {"totals", "payment_info"} and float(region["bbox"][1]) > body_min_y
    ]
    totals_start = int(round(min(totals_candidates))) if totals_candidates else int(round(percentile([region["bbox"][1] for region in image_space_regions], 0.9) + 500))

    horizontal_lines = detect_strong_horizontal_lines(binary_image)
    vertical_lines = detect_strong_vertical_lines(binary_image, max(0, int(prelim_top)), min(image_height, totals_start))

    top_cluster = choose_nearest_cluster(horizontal_lines, prelim_top, 120.0)
    top_y = int(top_cluster["best_position"]) if top_cluster else max(0, int(round(prelim_top)))

    header_bottom_target = percentile([float(region["bbox"][3]) for region in header_regions], 0.7) if header_regions else top_y + 120.0
    header_separator_cluster = choose_nearest_cluster(horizontal_lines, header_bottom_target, 120.0)
    header_separator_y = int(header_separator_cluster["best_position"]) if header_separator_cluster else int(round(header_bottom_target))

    bottom_search_min = int((main_body_end or header_separator_y) + 200)
    bottom_search_max = max(bottom_search_min + 50, totals_start - 60)
    bottom_candidates = [
        cluster
        for cluster in horizontal_lines
        if bottom_search_min <= cluster["best_position"] <= bottom_search_max
    ]
    if bottom_candidates:
        strongest_longest_run = max(cluster["best_longest_run"] for cluster in bottom_candidates)
        near_strongest = [
            cluster
            for cluster in bottom_candidates
            if cluster["best_longest_run"] >= strongest_longest_run * 0.85
        ]
        bottom_cluster = max(near_strongest, key=lambda cluster: cluster["best_position"])
    else:
        fallback_candidates = [cluster for cluster in horizontal_lines if cluster["best_position"] > header_separator_y + 200]
        bottom_cluster = max(fallback_candidates, key=lambda cluster: (cluster["best_longest_run"], cluster["best_total_dark"])) if fallback_candidates else None
    bottom_y = int(bottom_cluster["best_position"]) if bottom_cluster else max(header_separator_y + 200, totals_start - 120)

    left_cluster = choose_nearest_cluster(vertical_lines, prelim_left, 140.0)
    right_cluster = choose_nearest_cluster(vertical_lines, prelim_right, 140.0)
    left_x = int(left_cluster["best_position"]) if left_cluster else max(0, int(round(prelim_left)))
    right_x = int(right_cluster["best_position"]) if right_cluster else min(image_width - 1, int(round(prelim_right)))

    bbox = [left_x, top_y, right_x, bottom_y]
    normalized_bbox = {
        "x1": round(left_x / image_width, 6),
        "y1": round(top_y / image_height, 6),
        "x2": round(right_x / image_width, 6),
        "y2": round(bottom_y / image_height, 6),
    }

    def intersects_band(region: Dict[str, Any]) -> bool:
        x1, y1, x2, y2 = [float(value) for value in region.get("bbox", [0.0, 0.0, 0.0, 0.0])]
        return not (x2 < left_x or x1 > right_x or y2 < top_y or y1 > bottom_y)

    included_product_regions = [region for region in product_regions if intersects_band(region)]
    excluded_product_regions = [region for region in product_regions if not intersects_band(region)]
    inside_non_table_regions = [
        region
        for region in page_regions
        if region.get("zone") not in {"product_table_header", "product_table_body"} and intersects_band(region)
    ]
    non_table_intrusions = {}
    for region in inside_non_table_regions:
        zone_name = region.get("zone", "unknown")
        non_table_intrusions[zone_name] = non_table_intrusions.get(zone_name, 0) + 1

    product_coverage_ratio = len(included_product_regions) / max(1, len(product_regions))
    overflow_region_count = sum(1 for region in product_regions if float(region["bbox"][2]) > image_width)
    intrusion_penalty = min(0.2, len(inside_non_table_regions) * 0.01)
    confidence_score = round(max(0.5, min(0.98, 0.58 + product_coverage_ratio * 0.35 - intrusion_penalty)), 2)
    confidence = "high" if confidence_score >= 0.82 else "medium" if confidence_score >= 0.68 else "low"

    reasons = [
        f"used {len(product_regions)} page-{page_number} product-table header/body regions from zoning v2",
        f"snapped top border to a strong horizontal ruling line at y={top_y}",
        f"snapped left/right borders to strong vertical ruling lines at x={left_x} and x={right_x}",
        f"chose bottom separator at y={bottom_y} before the totals/payment block starting near y={totals_start}",
    ]
    if main_body_end and post_gap_start:
        reasons.append(f"largest body-text gap was {post_gap_start - main_body_end}px after the main item cluster")
    if overflow_region_count:
        reasons.append(f"ignored {overflow_region_count} right-side product regions with overflow coordinates during image-space snapping")

    band = {
        "band_id": f"page-{page_number:04d}-table-band-0001",
        "page": page_number,
        "scope": "layer_a_table_band_poc",
        "zone": "product_table_band",
        "bbox": bbox,
        "normalized_bbox": normalized_bbox,
        "header_separator_y": header_separator_y,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "reasons": reasons,
        "image_size": {"width": image_width, "height": image_height},
        "supporting_region_counts": {
            "product_regions_total": len(product_regions),
            "included_product_regions": len(included_product_regions),
            "excluded_product_regions": len(excluded_product_regions),
            "overflow_coordinate_regions": overflow_region_count,
            "non_table_regions_inside_band": len(inside_non_table_regions),
        },
        "supporting_lines": {
            "horizontal": {
                "top_y": top_y,
                "header_separator_y": header_separator_y,
                "bottom_y": bottom_y,
            },
            "vertical": {
                "left_x": left_x,
                "right_x": right_x,
                "candidate_columns": [cluster["best_position"] for cluster in vertical_lines],
            },
        },
        "non_table_intrusions": non_table_intrusions,
        "excluded_examples": [
            {
                "region_id": region["region_id"],
                "zone": region.get("zone"),
                "bbox": region.get("bbox"),
                "text": normalize_text(region.get("normalized_candidate_text") or "")[:120],
            }
            for region in excluded_product_regions[:10]
        ],
        "validation_image": str(validation_image_path.relative_to(run_dir)).replace("\\", "/"),
    }

    payload = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "implemented_layers": ["table_band_detection"],
            "excluded_layers": ["row_reconstruction", "column_reconstruction", "invoice_extraction"],
        },
        "bands": [band],
    }
    write_json(output_path, payload)
    build_table_band_validation_image(page_image_path, validation_image_path, band)

    summary_lines.extend(
        [
            "## Detected Band",
            "",
            f"- Band ID: `{band['band_id']}`",
            f"- BBox (image pixels): `{bbox}`",
            f"- Normalized BBox: `{normalized_bbox}`",
            f"- Confidence: `{confidence}` (`{confidence_score}`)",
            "",
            "## Reasons",
            "",
        ]
    )
    for reason in reasons:
        summary_lines.append(f"- {reason}")
    summary_lines.extend(
        [
            "",
            "## Validation",
            "",
            f"- Included product-table regions: `{len(included_product_regions)}` / `{len(product_regions)}`",
            f"- Excluded product-table regions: `{len(excluded_product_regions)}`",
            f"- Non-table regions intersecting the band: `{len(inside_non_table_regions)}`",
            f"- Validation overlay image: `{band['validation_image']}`",
            "",
            "## Notes",
            "",
            "- This proof of concept is intentionally limited to page 3 in staging.",
            "- The detector uses zoning-v2 regions to seed the search and page-image ruling lines to snap the final band.",
            "- No row, column, or invoice extraction logic is included here.",
        ]
    )
    write_markdown(summary_path, summary_lines)
    return payload


def region_intersects_bbox(region: Dict[str, Any], bbox: Sequence[float]) -> bool:
    x1, y1, x2, y2 = [float(value) for value in region.get("bbox", [0.0, 0.0, 0.0, 0.0])]
    bx1, by1, bx2, by2 = [float(value) for value in bbox]
    return not (x2 < bx1 or x1 > bx2 or y2 < by1 or y1 > by2)


def region_center_y(region: Dict[str, Any]) -> float:
    y1 = float(region.get("bbox", [0.0, 0.0, 0.0, 0.0])[1])
    y2 = float(region.get("bbox", [0.0, 0.0, 0.0, 0.0])[3])
    return (y1 + y2) / 2.0


def region_height_px(region: Dict[str, Any]) -> float:
    bbox = region.get("bbox", [0.0, 0.0, 0.0, 0.0])
    return max(1.0, float(bbox[3]) - float(bbox[1]))


def region_width_px(region: Dict[str, Any]) -> float:
    bbox = region.get("bbox", [0.0, 0.0, 0.0, 0.0])
    return max(1.0, float(bbox[2]) - float(bbox[0]))


def row_union_bbox(regions: Sequence[Dict[str, Any]], band_bbox: Sequence[float]) -> List[int]:
    xs1 = [float(region["bbox"][0]) for region in regions]
    ys1 = [float(region["bbox"][1]) for region in regions]
    xs2 = [float(region["bbox"][2]) for region in regions]
    ys2 = [float(region["bbox"][3]) for region in regions]
    bx1, by1, bx2, by2 = [float(value) for value in band_bbox]
    return [
        int(round(max(bx1, min(xs1)))),
        int(round(max(by1, min(ys1)))),
        int(round(min(bx2, max(xs2)))),
        int(round(min(by2, max(ys2)))),
    ]


def cluster_regions_into_rows(
    regions: Sequence[Dict[str, Any]],
    median_height: float,
) -> List[List[Dict[str, Any]]]:
    if not regions:
        return []
    ordered = sorted(regions, key=lambda region: (region_center_y(region), float(region["bbox"][1]), float(region["bbox"][0])))
    clusters: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = [ordered[0]]
    gap_threshold = max(18.0, median_height * 0.8)
    center_threshold = max(26.0, median_height * 0.95)
    for region in ordered[1:]:
        current_centers = [region_center_y(item) for item in current]
        current_center = percentile(current_centers, 0.5)
        current_y2 = max(float(item["bbox"][3]) for item in current)
        region_y1 = float(region["bbox"][1])
        if region_y1 <= current_y2 + gap_threshold and abs(region_center_y(region) - current_center) <= center_threshold:
            current.append(region)
            continue
        clusters.append(sorted(current, key=lambda item: float(item["bbox"][0])))
        current = [region]
    clusters.append(sorted(current, key=lambda item: float(item["bbox"][0])))
    return clusters


def aggregate_row_candidates_by_engine(regions: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_engine: Dict[str, List[Dict[str, Any]]] = {}
    for region in regions:
        raw_candidates = region.get("raw_candidates", {})
        for engine_name, candidate in raw_candidates.items():
            by_engine.setdefault(engine_name, []).append(
                {
                    "region_id": region.get("region_id"),
                    "text": candidate.get("text", ""),
                    "confidence": candidate.get("confidence"),
                    "classification": region.get("classification"),
                }
            )
    for engine_name in by_engine:
        by_engine[engine_name] = sorted(
            by_engine[engine_name],
            key=lambda item: next(
                float(region["bbox"][0])
                for region in regions
                if region.get("region_id") == item["region_id"]
            ),
        )
    return by_engine


def confidence_to_unit(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return None
    if numeric > 1.0:
        numeric = numeric / 100.0
    if numeric < 0:
        return None
    if numeric > 1:
        numeric = 1.0
    return numeric


def average_region_confidence(regions: Sequence[Dict[str, Any]]) -> float:
    values: List[float] = []
    for region in regions:
        raw_candidates = region.get("raw_candidates", {})
        region_values = [confidence_to_unit(candidate.get("confidence")) for candidate in raw_candidates.values()]
        region_values = [value for value in region_values if value is not None]
        if region_values:
            values.append(max(region_values))
    if not values:
        return 0.0
    return sum(values) / len(values)


def row_engine_diversity(regions: Sequence[Dict[str, Any]]) -> int:
    return len({engine for region in regions for engine in region.get("source_engines_present", [])})


def row_text_density(regions: Sequence[Dict[str, Any]], band_bbox: Sequence[float]) -> float:
    band_width = max(1.0, float(band_bbox[2]) - float(band_bbox[0]))
    text_width = sum(region_width_px(region) for region in regions if normalize_text(region.get("normalized_candidate_text") or ""))
    return min(1.0, text_width / band_width)


def row_confidence_label(score: float) -> str:
    if score >= 0.82:
        return "high"
    if score >= 0.62:
        return "medium"
    return "low"


def build_row_notes(
    row_regions: Sequence[Dict[str, Any]],
    row_bbox: Sequence[int],
    row_index: int,
    total_rows: int,
    median_height: float,
    product_zone_ratio: float,
    gap_before: Optional[float],
    gap_after: Optional[float],
    row_type: str = "body",
    avg_confidence: float = 0.0,
    text_density: float = 0.0,
    engine_diversity: int = 0,
) -> List[str]:
    notes: List[str] = []
    row_height = float(row_bbox[3]) - float(row_bbox[1])
    if row_type == "header":
        notes.append("header row candidate")
    else:
        notes.append("body row candidate from geometric clustering")
    if row_type == "body" and row_height > median_height * 1.8:
        notes.append("tall row span may indicate merged content")
    if row_type == "body" and row_height < median_height * 0.75:
        notes.append("short row span may indicate split fragment")
    if product_zone_ratio < 0.55:
        notes.append("mixed zone membership inside row")
    if row_type == "body" and gap_before is not None and gap_before < median_height * 0.45:
        notes.append("small leading gap to previous row suggests possible split")
    if row_type == "body" and gap_after is not None and gap_after < median_height * 0.45:
        notes.append("small trailing gap to next row suggests possible split")
    if row_index == total_rows - 1 and len(row_regions) <= 2:
        notes.append("trailing sparse row candidate")
    if row_type == "body" and avg_confidence < 0.55 and engine_diversity <= 1:
        notes.append("low-confidence single-engine row candidate")
    if row_type == "body" and text_density < 0.16:
        notes.append("low text-density row candidate")
    return notes


def row_to_csv_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    csv_rows: List[Dict[str, Any]] = []
    for row in rows:
        csv_rows.append(
            {
                "row_id": row["row_id"],
                "page": row["page"],
                "row_type": row.get("row_type", ""),
                "row_confidence": row["row_confidence"],
                "row_confidence_level": row.get("row_confidence_level", ""),
                "region_count": row["region_count"],
                "conflict_count": row["conflict_count"],
                "row_bbox_x1": row["row_bbox"][0],
                "row_bbox_y1": row["row_bbox"][1],
                "row_bbox_x2": row["row_bbox"][2],
                "row_bbox_y2": row["row_bbox"][3],
                "source_region_ids": ",".join(row.get("source_region_ids", [])),
                "notes": " | ".join(row.get("notes", [])),
            }
        )
    return csv_rows


def build_table_row_summary(output_path: Path, summary: Dict[str, Any]) -> None:
    lines = [
        "# Table Row Summary",
        "",
        f"Generated: {now_iso()}",
        "",
        "- Scope: `Layer B only`",
        f"- Page: `{summary.get('page')}`",
        f"- Band ID: `{summary.get('band_id')}`",
        "",
        "## Overview",
        "",
        f"- Rows detected: `{summary.get('row_count', 0)}`",
        f"- Average row confidence: `{summary.get('average_row_confidence', 0.0)}`",
        f"- Validation overlay image: `{summary.get('validation_image', '')}`",
        "",
        "## Highest Confidence Rows",
        "",
    ]
    for row in summary.get("highest_confidence_rows", []):
        lines.append(
            f"- `{row['row_id']}` confidence `{row['row_confidence']}` bbox `{row['row_bbox']}` "
            f"regions `{row['region_count']}` conflicts `{row['conflict_count']}`"
        )
    lines.extend(["", "## Lowest Confidence Rows", ""])
    for row in summary.get("lowest_confidence_rows", []):
        lines.append(
            f"- `{row['row_id']}` confidence `{row['row_confidence']}` bbox `{row['row_bbox']}` "
            f"notes `{'; '.join(row.get('notes', []))}`"
        )
    lines.extend(["", "## Correctly Reconstructed Examples", ""])
    for example in summary.get("correct_examples", []):
        lines.append(
            f"- `{example['row_id']}` bbox `{example['row_bbox']}` reasons `{'; '.join(example.get('notes', []))}`"
        )
    lines.extend(["", "## Possible Split Rows", ""])
    split_examples = summary.get("possible_split_rows", [])
    if not split_examples:
        lines.append("- None flagged.")
    else:
        for example in split_examples:
            lines.append(
                f"- `{example['row_id']}` confidence `{example['row_confidence']}` notes `{'; '.join(example.get('notes', []))}`"
            )
    lines.extend(["", "## Possible Merged Rows", ""])
    merged_examples = summary.get("possible_merged_rows", [])
    if not merged_examples:
        lines.append("- None flagged.")
    else:
        for example in merged_examples:
            lines.append(
                f"- `{example['row_id']}` confidence `{example['row_confidence']}` notes `{'; '.join(example.get('notes', []))}`"
            )
    lines.extend(["", "## Omitted Row Candidates", ""])
    omitted = summary.get("omitted_row_candidates", [])
    if not omitted:
        lines.append("- None omitted.")
    else:
        for candidate in omitted:
            lines.append(
                f"- bbox `{candidate['row_bbox']}` regions `{candidate['region_count']}` "
                f"avg_conf `{candidate['average_region_confidence']}` reasons `{'; '.join(candidate.get('reasons', []))}`"
            )
    write_markdown(output_path, lines)


def omitted_candidate_key(candidate: Dict[str, Any]) -> str:
    bbox = candidate.get("row_bbox", [])
    bbox_part = "-".join(str(int(round(float(value)))) for value in bbox)
    region_part = ",".join(candidate.get("source_region_ids", []))
    return f"bbox-{bbox_part}|regions-{region_part}"


def build_table_row_validation_image(
    image_path: Path,
    output_path: Path,
    band: Dict[str, Any],
    rows: Sequence[Dict[str, Any]],
) -> None:
    pil_image, pil_err = import_optional("PIL.Image")
    draw_module, draw_err = import_optional("PIL.ImageDraw")
    if pil_err or draw_err:
        return
    image = pil_image.open(str(image_path)).convert("RGBA")
    overlay = pil_image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = draw_module.Draw(overlay)
    x1, y1, x2, y2 = [int(value) for value in band["bbox"]]
    draw.rectangle((x1, y1, x2, y2), outline=(31, 111, 235, 255), width=5, fill=(31, 111, 235, 24))
    palette = [
        ((21, 127, 59, 255), (21, 127, 59, 30)),
        ((31, 111, 235, 255), (31, 111, 235, 30)),
        ((154, 103, 0, 255), (154, 103, 0, 30)),
        ((201, 60, 55, 255), (201, 60, 55, 24)),
    ]
    for index, row in enumerate(rows):
        stroke, fill = palette[index % len(palette)]
        rx1, ry1, rx2, ry2 = [int(value) for value in row["row_bbox"]]
        draw.rectangle((rx1, ry1, rx2, ry2), outline=stroke, width=4, fill=fill)
        label_top = max(8, ry1 + 6)
        label = f"{row['row_id'].split('-')[-1]} | {row['row_confidence']}"
        draw.rectangle((rx1 + 6, label_top, min(rx1 + 168, image.size[0] - 8), label_top + 24), fill=(15, 23, 42, 215))
        draw.text((rx1 + 12, label_top + 5), label, fill=(255, 255, 255, 255))
    merged = pil_image.alpha_composite(image, overlay).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.save(str(output_path))


def run_table_row_reconstruction_poc(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    fusion_dir = run_dir / "fusion"
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    fused_regions = read_json(fusion_dir / "fused_regions.json", [])
    zoned_regions = read_json(fusion_dir / "zoned_regions_v2.json", [])
    table_bands_payload = read_json(tables_dir / "table_bands.json", {"bands": []})
    page_image_path = run_dir / "pages" / f"page-{page_number:04d}.png"
    bands = table_bands_payload.get("bands", [])
    band = next((item for item in bands if item.get("band_id") == band_id and int(item.get("page", 0)) == page_number), None)

    rows_json_path = tables_dir / "table_rows.json"
    rows_csv_path = tables_dir / "table_rows.csv"
    rows_summary_path = tables_dir / "table_row_summary.md"
    validation_image_path = tables_dir / f"table_rows_page-{page_number:04d}_validation.png"

    if not band:
        payload = {
            "created_at": now_iso(),
            "status": "missing_table_band",
            "page": page_number,
            "band_id": band_id,
            "rows": [],
        }
        write_json(rows_json_path, payload)
        write_csv(rows_csv_path, [])
        build_table_row_summary(rows_summary_path, {"page": page_number, "band_id": band_id})
        return payload

    zoned_by_id = {region.get("region_id"): region for region in zoned_regions if region.get("region_id")}
    page_regions = []
    for region in fused_regions:
        if int(region.get("page", 0)) != page_number:
            continue
        if not region_intersects_bbox(region, band["bbox"]):
            continue
        zone_region = zoned_by_id.get(region.get("region_id"), {})
        enriched = {**region, **{key: zone_region.get(key) for key in ["zone", "zone_confidence", "zone_reasons", "why_unknown", "suggested_zone"]}}
        page_regions.append(enriched)

    product_regions = [region for region in page_regions if region.get("zone") in {"product_table_header", "product_table_body"}]
    if not product_regions:
        payload = {
            "created_at": now_iso(),
            "status": "no_product_regions_in_band",
            "page": page_number,
            "band_id": band_id,
            "rows": [],
        }
        write_json(rows_json_path, payload)
        write_csv(rows_csv_path, [])
        build_table_row_summary(rows_summary_path, {"page": page_number, "band_id": band_id})
        return payload

    header_separator_y = float(band.get("header_separator_y") or band["bbox"][1])
    median_height = percentile([region_height_px(region) for region in product_regions], 0.5)
    header_min_y = min(float(region["bbox"][1]) for region in product_regions if region.get("zone") == "product_table_header")
    row_search_top = header_min_y - 8.0
    header_candidate_bottom = header_separator_y + max(6.0, median_height * 0.15)
    body_start_y = header_separator_y + max(28.0, median_height * 0.55)

    body_regions = [region for region in product_regions if region.get("zone") == "product_table_body"]
    ordered_body = sorted(body_regions, key=lambda region: float(region["bbox"][1]))
    body_cutoff_y = max(float(band["bbox"][3]), header_separator_y)
    if len(ordered_body) >= 2:
        largest_gap = 0.0
        gap_end_y = None
        for left, right in zip(ordered_body, ordered_body[1:]):
            gap = float(right["bbox"][1]) - float(left["bbox"][3])
            if gap > largest_gap:
                largest_gap = gap
                gap_end_y = float(left["bbox"][3])
        if gap_end_y is not None and largest_gap > max(140.0, median_height * 2.2):
            body_cutoff_y = gap_end_y + max(12.0, median_height * 0.4)

    row_candidates = [
        region
        for region in page_regions
        if region_center_y(region) >= row_search_top
        and float(region["bbox"][1]) <= body_cutoff_y
        and region.get("zone") in {"product_table_header", "product_table_body"}
    ]

    header_candidates = [
        region
        for region in row_candidates
        if region.get("zone") == "product_table_header"
        and region_center_y(region) <= header_candidate_bottom
    ]
    body_candidates = [
        region
        for region in row_candidates
        if region.get("zone") == "product_table_body"
        and float(region["bbox"][1]) >= body_start_y
    ]

    row_clusters: List[Tuple[str, List[Dict[str, Any]]]] = []
    if header_candidates:
        row_clusters.append(("header", sorted(header_candidates, key=lambda region: float(region["bbox"][0]))))
    row_clusters.extend(("body", cluster) for cluster in cluster_regions_into_rows(body_candidates, median_height))

    rows: List[Dict[str, Any]] = []
    omitted_row_candidates: List[Dict[str, Any]] = []
    for row_type, cluster in row_clusters:
        row_bbox = row_union_bbox(cluster, band["bbox"])
        avg_conf = average_region_confidence(cluster)
        text_density = row_text_density(cluster, band["bbox"])
        engine_diversity = row_engine_diversity(cluster)
        x1, _, x2, _ = [float(value) for value in row_bbox]
        band_width = max(1.0, float(band["bbox"][2]) - float(band["bbox"][0]))
        x_span_ratio = (x2 - x1) / band_width
        left_coverage = min(float(region["bbox"][0]) for region in cluster) <= float(band["bbox"][0]) + band_width * 0.18
        right_coverage = max(float(region["bbox"][2]) for region in cluster) >= float(band["bbox"][0]) + band_width * 0.72
        product_zone_ratio = sum(1 for region in cluster if region.get("zone") in {"product_table_header", "product_table_body"}) / max(1, len(cluster))
        conflict_count = sum(1 for region in cluster if region.get("classification") == "conflicting")

        score = 0.32
        score += min(0.22, len(cluster) * 0.03)
        score += min(0.14, x_span_ratio * 0.2)
        if left_coverage and right_coverage:
            score += 0.12
        score += min(0.12, avg_conf * 0.12)
        score += product_zone_ratio * 0.1
        if conflict_count:
            score -= min(0.1, conflict_count * 0.025)
        if len(cluster) <= 2:
            score -= 0.1
        if row_type == "body" and avg_conf < 0.55 and engine_diversity <= 1:
            score -= 0.16
        if row_type == "body" and text_density < 0.16:
            score -= 0.12
        row_height = float(row_bbox[3]) - float(row_bbox[1])
        if row_height > median_height * 1.8:
            score -= 0.06
        if row_height < median_height * 0.75:
            score -= 0.08
        row_confidence = round(max(0.18, min(0.95, score)), 2)

        omit_reasons = []
        if row_type == "body" and avg_conf < 0.55 and engine_diversity <= 1 and text_density < 0.55:
            omit_reasons.append("lower body candidate has low-confidence single-engine evidence")
        if row_type == "body" and len(cluster) < 3:
            omit_reasons.append("body candidate below minimum region-density threshold")
        if omit_reasons:
            omitted_row_candidates.append(
                {
                    "row_type": row_type,
                    "row_bbox": row_bbox,
                    "source_region_ids": [region["region_id"] for region in cluster],
                    "region_count": len(cluster),
                    "average_region_confidence": round(avg_conf, 2),
                    "text_density": round(text_density, 2),
                    "engine_diversity": engine_diversity,
                    "reasons": omit_reasons,
                }
            )
            continue

        index = len(rows) + 1

        rows.append(
            {
                "row_id": f"page-{page_number:04d}-row-{index:04d}",
                "page": page_number,
                "band_id": band_id,
                "row_type": row_type,
                "row_bbox": row_bbox,
                "normalized_row_bbox": {
                    "x1": round(row_bbox[0] / float(band["image_size"]["width"]), 6),
                    "y1": round(row_bbox[1] / float(band["image_size"]["height"]), 6),
                    "x2": round(row_bbox[2] / float(band["image_size"]["width"]), 6),
                    "y2": round(row_bbox[3] / float(band["image_size"]["height"]), 6),
                },
                "row_confidence": row_confidence,
                "row_confidence_level": row_confidence_label(row_confidence),
                "source_region_ids": [region["region_id"] for region in cluster],
                "region_count": len(cluster),
                "conflict_count": conflict_count,
                "text_density": round(text_density, 2),
                "engine_diversity": engine_diversity,
                "average_region_confidence": round(avg_conf, 2),
                "candidate_texts_by_engine": aggregate_row_candidates_by_engine(cluster),
                "region_snapshots": [
                    {
                        "region_id": region["region_id"],
                        "bbox": region["bbox"],
                        "classification": region.get("classification"),
                        "zone": region.get("zone"),
                        "normalized_candidate_text": region.get("normalized_candidate_text"),
                        "source_engines_present": region.get("source_engines_present", []),
                    }
                    for region in cluster
                ],
                "notes": [],
            }
        )

    for index, row in enumerate(rows):
        previous_gap = None
        next_gap = None
        if index > 0:
            previous_gap = float(row["row_bbox"][1]) - float(rows[index - 1]["row_bbox"][3])
        if index < len(rows) - 1:
            next_gap = float(rows[index + 1]["row_bbox"][1]) - float(row["row_bbox"][3])
        row_regions = [region for region in page_regions if region["region_id"] in set(row["source_region_ids"])]
        product_zone_ratio = sum(1 for region in row_regions if region.get("zone") in {"product_table_header", "product_table_body"}) / max(1, len(row_regions))
        row["notes"] = build_row_notes(
            row_regions,
            row["row_bbox"],
            index,
            len(rows),
            median_height,
            product_zone_ratio,
            previous_gap,
            next_gap,
            row.get("row_type", "body"),
            row.get("average_region_confidence", 0.0),
            row.get("text_density", 0.0),
            row.get("engine_diversity", 0),
        )

    average_confidence = round(sum(row["row_confidence"] for row in rows) / max(1, len(rows)), 2)
    highest_confidence_rows = sorted(rows, key=lambda row: row["row_confidence"], reverse=True)[:3]
    lowest_confidence_rows = sorted(rows, key=lambda row: row["row_confidence"])[:3]
    correct_examples = [row for row in rows if row["row_confidence"] >= 0.72][:3]
    possible_split_rows = [
        row
        for row in rows
        if any("split" in note for note in row.get("notes", []))
    ][:4]
    possible_merged_rows = [
        row
        for row in rows
        if any("merged" in note for note in row.get("notes", []))
    ][:4]

    payload = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "implemented_layers": ["row_reconstruction"],
            "excluded_layers": ["column_reconstruction", "invoice_extraction"],
        },
        "page": page_number,
        "band_id": band_id,
        "row_count": len(rows),
        "average_row_confidence": average_confidence,
        "body_cutoff_y": body_cutoff_y,
        "header_separator_y": header_separator_y,
        "body_start_y": body_start_y,
        "omitted_row_candidates": omitted_row_candidates,
        "validation_image": str(validation_image_path.relative_to(run_dir)).replace("\\", "/") if page_image_path.exists() else None,
        "rows": rows,
        "summary": {
            "highest_confidence_rows": highest_confidence_rows,
            "lowest_confidence_rows": lowest_confidence_rows,
            "correct_examples": correct_examples,
            "possible_split_rows": possible_split_rows,
            "possible_merged_rows": possible_merged_rows,
            "omitted_row_candidates": omitted_row_candidates,
        },
    }
    write_json(rows_json_path, payload)
    write_csv(rows_csv_path, row_to_csv_rows(rows))
    if page_image_path.exists():
        build_table_row_validation_image(page_image_path, validation_image_path, band, rows)
    build_table_row_summary(
        rows_summary_path,
        {
            "page": page_number,
            "band_id": band_id,
            "row_count": len(rows),
            "average_row_confidence": average_confidence,
            "validation_image": payload.get("validation_image"),
            "highest_confidence_rows": highest_confidence_rows,
            "lowest_confidence_rows": lowest_confidence_rows,
            "correct_examples": correct_examples,
            "possible_split_rows": possible_split_rows,
            "possible_merged_rows": possible_merged_rows,
            "omitted_row_candidates": omitted_row_candidates,
        },
    )
    return payload


def validate_layer_b_readiness(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    tables_dir = run_dir / "tables"
    rows_json_path = tables_dir / "table_rows.json"
    rows_csv_path = tables_dir / "table_rows.csv"
    rows_summary_path = tables_dir / "table_row_summary.md"
    fused_regions_path = run_dir / "fusion" / "fused_regions.json"
    row_review_path = tables_dir / "table_row_review_decisions.json"
    issues: List[str] = []

    for path in [rows_json_path, rows_csv_path, rows_summary_path]:
        if not path.exists():
            issues.append(f"missing required Layer B artifact: {path.relative_to(run_dir)}")

    rows_payload = read_json(rows_json_path, {})
    fused_regions = read_json(fused_regions_path, [])
    fused_region_ids = {region.get("region_id") for region in fused_regions if region.get("region_id")}
    rows = rows_payload.get("rows", []) if isinstance(rows_payload, dict) else []

    if rows_payload:
        if rows_payload.get("status") != "ok":
            issues.append(f"table_rows.json status is {rows_payload.get('status')!r}, expected 'ok'")
        scope = rows_payload.get("scope", {})
        if scope.get("implemented_layers") != ["row_reconstruction"]:
            issues.append("Layer B scope does not say implemented_layers == ['row_reconstruction']")
        excluded_layers = set(scope.get("excluded_layers", []))
        if not {"column_reconstruction", "invoice_extraction"}.issubset(excluded_layers):
            issues.append("Layer B scope does not explicitly exclude column reconstruction and invoice extraction")
        if int(rows_payload.get("page", 0)) != page_number:
            issues.append(f"Layer B page is {rows_payload.get('page')!r}, expected {page_number}")
        if rows_payload.get("band_id") != band_id:
            issues.append(f"Layer B band_id is {rows_payload.get('band_id')!r}, expected {band_id}")

    if not rows:
        issues.append("table_rows.json has no rows")

    forbidden_row_keys = {
        "columns",
        "cells",
        "fields",
        "line_items",
        "invoice_number",
        "invoice_date",
        "vendor",
        "customer",
        "products",
        "normalized_values",
    }
    for row in rows:
        row_id = row.get("row_id", "<missing row_id>")
        for key in ["row_id", "row_bbox", "normalized_row_bbox", "source_region_ids", "row_confidence", "notes"]:
            if key not in row:
                issues.append(f"{row_id} missing required key: {key}")
        if forbidden_row_keys.intersection(row.keys()):
            issues.append(f"{row_id} contains column/business-meaning keys: {sorted(forbidden_row_keys.intersection(row.keys()))}")
        quality_notes = " | ".join(row.get("notes", []))
        if "tall row span may indicate merged content" in quality_notes:
            issues.append(f"{row_id} is still flagged as a likely merged row")
        if "low-confidence single-engine row candidate" in quality_notes:
            issues.append(f"{row_id} has low-confidence single-engine evidence")
        if "low text-density row candidate" in quality_notes:
            issues.append(f"{row_id} has low text-density evidence")
        for region_id in row.get("source_region_ids", []):
            if region_id not in fused_region_ids:
                issues.append(f"{row_id} references unknown fused region_id: {region_id}")

    row_review_payload = read_json(row_review_path, {"decisions": []})
    row_review_decisions = {
        decision.get("candidate_key"): decision
        for decision in row_review_payload.get("decisions", [])
        if decision.get("candidate_key")
    }
    omitted = rows_payload.get("omitted_row_candidates", []) if isinstance(rows_payload, dict) else []
    for candidate in omitted:
        candidate_key = omitted_candidate_key(candidate)
        decision = row_review_decisions.get(candidate_key)
        if not decision:
            issues.append(f"Layer B omitted candidate {candidate_key} requires a recorded review decision before Layer C")
            continue
        classification = decision.get("classification")
        if classification == "real_product_row":
            issues.append(f"Layer B omitted candidate {candidate_key} was reviewed as a real product row; fix Layer B before Layer C")
        elif classification == "unclear_needs_manual_review":
            issues.append(f"Layer B omitted candidate {candidate_key} remains unclear after review; manual review required before Layer C")
        elif classification not in {"ocr_noise_non_table", "continuation_not_standalone"}:
            issues.append(f"Layer B omitted candidate {candidate_key} has unsupported review classification: {classification!r}")

    return {
        "created_at": now_iso(),
        "status": "ok" if not issues else "blocked",
        "issues": issues,
        "row_count": len(rows),
        "rows": rows,
        "rows_payload": rows_payload,
        "fused_regions": fused_regions,
        "row_review_decisions": row_review_payload.get("decisions", []),
    }


def build_table_column_readiness_report(output_path: Path, readiness: Dict[str, Any]) -> None:
    lines = [
        "# Layer C Readiness",
        "",
        f"Generated: {now_iso()}",
        "",
        f"- Status: `{readiness.get('status')}`",
        f"- Layer B rows available: `{readiness.get('row_count', 0)}`",
        "",
        "## Issues",
        "",
    ]
    issues = readiness.get("issues", [])
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- Layer B passed the readiness gate.")
    lines.extend(
        [
            "",
            "## Gate Decision",
            "",
            "- Layer C may run only when status is `ok`.",
            "- This report does not create column artifacts when Layer B is blocked.",
        ]
    )
    write_markdown(output_path, lines)


def cluster_x_positions(values: Sequence[Dict[str, Any]], tolerance: float) -> List[Dict[str, Any]]:
    if not values:
        return []
    ordered = sorted(values, key=lambda item: float(item["x"]))
    clusters: List[List[Dict[str, Any]]] = []
    current = [ordered[0]]
    for item in ordered[1:]:
        current_center = sum(float(entry["x"]) for entry in current) / len(current)
        if abs(float(item["x"]) - current_center) <= tolerance:
            current.append(item)
            continue
        clusters.append(current)
        current = [item]
    clusters.append(current)

    result = []
    for cluster in clusters:
        rows = sorted({entry["row_id"] for entry in cluster})
        region_ids = sorted({entry["region_id"] for entry in cluster})
        result.append(
            {
                "x": round(sum(float(entry["x"]) for entry in cluster) / len(cluster), 2),
                "support_count": len(cluster),
                "row_support_count": len(rows),
                "row_ids": rows,
                "source_region_ids": region_ids,
                "edge_types": sorted({entry["edge_type"] for entry in cluster}),
            }
        )
    return result


def column_confidence_label(score: float) -> str:
    if score >= 0.82:
        return "high"
    if score >= 0.62:
        return "medium"
    return "low"


def aggregate_region_candidates_by_engine(regions: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return aggregate_row_candidates_by_engine(regions)


def horizontal_overlap_ratio(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ax2 = float(a[0]), float(a[2])
    bx1, bx2 = float(b[0]), float(b[2])
    overlap = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    width = max(1.0, ax2 - ax1)
    return overlap / width


def table_cell_confidence(regions: Sequence[Dict[str, Any]], column_confidence: float, notes: Sequence[str]) -> float:
    if not regions:
        return 0.0
    avg_conf = average_region_confidence(regions)
    conflict_penalty = 0.08 if any(region.get("classification") == "conflicting" for region in regions) else 0.0
    note_penalty = min(0.16, len(notes) * 0.04)
    return round(max(0.18, min(0.95, column_confidence * 0.45 + avg_conf * 0.55 - conflict_penalty - note_penalty)), 2)


def detect_column_ruling_lines(run_dir: Path, band: Dict[str, Any]) -> List[Dict[str, Any]]:
    page_number = int(band.get("page", 0))
    page_image_path = run_dir / "pages" / f"page-{page_number:04d}.png"
    pil_image, pil_err = import_optional("PIL.Image")
    numpy_module, np_err = import_optional("numpy")
    if pil_err or np_err or not page_image_path.exists():
        return []
    image = numpy_module.array(pil_image.open(str(page_image_path)).convert("L"))
    binary_image = (image < 180).astype("uint8")
    _, by1, _, by2 = [float(value) for value in band["bbox"]]
    vertical_lines = detect_strong_vertical_lines(binary_image, max(0, int(by1)), min(image.shape[0], int(by2)))
    bx1, _, bx2, _ = [float(value) for value in band["bbox"]]
    lines = []
    for line in vertical_lines:
        x = float(line["best_position"])
        if bx1 - 8.0 <= x <= bx2 + 8.0:
            lines.append(
                {
                    "x": round(max(bx1, min(bx2, x)), 2),
                    "source": "vertical_ruling_line",
                    "support_count": line.get("best_total_dark"),
                    "longest_run": line.get("best_longest_run"),
                }
            )
    return lines


def merge_column_boundary_signals(signals: Sequence[Dict[str, Any]], tolerance: float) -> List[Dict[str, Any]]:
    if not signals:
        return []
    ordered = sorted(signals, key=lambda item: float(item["x"]))
    clusters: List[List[Dict[str, Any]]] = []
    current = [ordered[0]]
    for signal in ordered[1:]:
        center = sum(float(item["x"]) for item in current) / len(current)
        if abs(float(signal["x"]) - center) <= tolerance:
            current.append(signal)
            continue
        clusters.append(current)
        current = [signal]
    clusters.append(current)

    merged = []
    for cluster in clusters:
        ruling = [item for item in cluster if item.get("source") == "vertical_ruling_line"]
        x = (
            sum(float(item["x"]) for item in ruling) / len(ruling)
            if ruling
            else sum(float(item["x"]) for item in cluster) / len(cluster)
        )
        merged.append(
            {
                "x": round(x, 2),
                "sources": sorted({item.get("source", "unknown") for item in cluster}),
                "support_count": len(cluster),
                "row_ids": sorted({row_id for item in cluster for row_id in item.get("row_ids", [])}),
                "source_region_ids": sorted({region_id for item in cluster for region_id in item.get("source_region_ids", [])}),
            }
        )
    return merged


def build_table_column_validation_image(
    image_path: Path,
    output_path: Path,
    band: Dict[str, Any],
    columns: Sequence[Dict[str, Any]],
    row_groups: Sequence[Dict[str, Any]],
) -> None:
    pil_image, pil_err = import_optional("PIL.Image")
    draw_module, draw_err = import_optional("PIL.ImageDraw")
    if pil_err or draw_err or not image_path.exists():
        return
    image = pil_image.open(str(image_path)).convert("RGBA")
    overlay = pil_image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = draw_module.Draw(overlay)
    x1, y1, x2, y2 = [int(value) for value in band["bbox"]]
    draw.rectangle((x1, y1, x2, y2), outline=(31, 111, 235, 255), width=5, fill=(31, 111, 235, 20))
    for column in columns:
        bx1 = int(round(column["bbox"][0]))
        bx2 = int(round(column["bbox"][2]))
        fill = (22, 163, 74, 30) if column.get("confidence_level") != "low" else (234, 179, 8, 28)
        draw.rectangle((bx1, y1, bx2, y2), outline=(22, 163, 74, 210), width=3, fill=fill)
        draw.text((bx1 + 6, y1 + 8), column["column_id"].split("-")[-1], fill=(15, 23, 42, 255))
    for row_group in row_groups:
        for assignment in row_group.get("cells", []):
            for snapshot in assignment.get("region_snapshots", []):
                rx1, ry1, rx2, ry2 = [int(round(value)) for value in snapshot.get("bbox", [0, 0, 0, 0])]
                draw.rectangle((rx1, ry1, rx2, ry2), outline=(220, 38, 38, 190), width=2)
    label = "LAYER C COLUMN GEOMETRY POC"
    draw.rectangle((x1 + 10, max(10, y1 + 10), min(x1 + 500, image.size[0] - 10), max(10, y1 + 44)), fill=(15, 23, 42, 210))
    draw.text((x1 + 18, max(16, y1 + 16)), label, fill=(255, 255, 255, 255))
    merged = pil_image.alpha_composite(image, overlay).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.save(str(output_path))


def table_column_csv_rows(columns: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    csv_rows: List[Dict[str, Any]] = []
    for column in columns:
        csv_rows.append(
            {
                "column_id": column["column_id"],
                "page": column["page"],
                "band_id": column["band_id"],
                "bbox_x1": column["bbox"][0],
                "bbox_y1": column["bbox"][1],
                "bbox_x2": column["bbox"][2],
                "bbox_y2": column["bbox"][3],
                "stability_score": column.get("stability_score"),
                "confidence_level": column.get("confidence_level", ""),
                "cells_total": column.get("cell_counts", {}).get("total", 0),
                "cells_empty": column.get("cell_counts", {}).get("empty", 0),
                "cells_conflicting": column.get("cell_counts", {}).get("conflicting", 0),
                "boundary_sources": ",".join(column.get("boundary_sources", [])),
                "notes": " | ".join(column.get("notes", [])),
            }
        )
    return csv_rows


def table_cell_csv_rows(cells: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    csv_rows: List[Dict[str, Any]] = []
    for cell in cells:
        csv_rows.append(
            {
                "cell_id": cell["cell_id"],
                "row_id": cell["row_id"],
                "row_type": cell.get("row_type", ""),
                "column_id": cell["column_id"],
                "cell_status": cell["cell_status"],
                "region_count": cell["region_count"],
                "has_conflict": cell["has_conflict"],
                "cell_confidence": cell["cell_confidence"],
                "source_region_ids": ",".join(cell.get("source_region_ids", [])),
                "notes": " | ".join(cell.get("notes", [])),
            }
        )
    return csv_rows


def build_table_column_summary(output_path: Path, payload: Dict[str, Any]) -> None:
    lines = [
        "# Table Column Summary",
        "",
        f"Generated: {now_iso()}",
        "",
        "- Scope: `Layer C only`",
        f"- Page: `{payload.get('page')}`",
        f"- Band ID: `{payload.get('band_id')}`",
        "",
        "## Overview",
        "",
        f"- Columns detected: `{payload.get('column_count', 0)}`",
        f"- Rows modeled: `{payload.get('row_count', 0)}`",
        f"- Cells modeled: `{payload.get('cell_count', 0)}`",
        f"- Empty cells: `{payload.get('validation', {}).get('empty_cell_count', 0)}`",
        f"- Conflicting cells: `{payload.get('validation', {}).get('conflicting_cell_count', 0)}`",
        f"- Validation overlay image: `{payload.get('validation_image', '')}`",
        "",
        "## Columns",
        "",
    ]
    for column in payload.get("columns", []):
        lines.append(
            f"- `{column['column_id']}` boundaries `{column['boundaries']}` stability `{column['stability_score']}` "
            f"cells `{column.get('cell_counts', {}).get('total', 0)}` empty `{column.get('cell_counts', {}).get('empty', 0)}` "
            f"conflicts `{column.get('cell_counts', {}).get('conflicting', 0)}` sources `{', '.join(column.get('boundary_sources', []))}`"
        )
    missing = payload.get("validation", {}).get("missing_cells", [])
    lines.extend(["", "## Missing Cells", ""])
    if not missing:
        lines.append("- None flagged.")
    else:
        for cell in missing[:30]:
            lines.append(f"- `{cell['cell_id']}` row `{cell['row_id']}` column `{cell['column_id']}`")
    conflicting = payload.get("validation", {}).get("conflicting_cells", [])
    lines.extend(["", "## Conflicting Cells", ""])
    if not conflicting:
        lines.append("- None flagged.")
    else:
        for cell in conflicting[:30]:
            lines.append(
                f"- `{cell['cell_id']}` row `{cell['row_id']}` column `{cell['column_id']}` "
                f"regions `{','.join(cell.get('source_region_ids', []))}`"
            )
    write_markdown(output_path, lines)


def build_table_column_review_markdown(output_path: Path, payload: Dict[str, Any]) -> None:
    lines = [
        "# Table Column Review Decisions",
        "",
        f"Generated: {payload.get('created_at')}",
        "",
        "## Layer C Column Geometry Review",
        "",
        f"- Reviewed artifact: `{payload.get('reviewed_artifact')}`",
        f"- Decision: `{payload.get('decision')}`",
        f"- Accepted column count: `{payload.get('accepted_column_count')}`",
        f"- Reviewer timestamp: `{payload.get('reviewer_timestamp')}`",
        "",
        "## Notes",
        "",
        payload.get("notes", ""),
        "",
        "## Scope",
        "",
        "- Geometry acceptance only.",
        "- No semantic column labels are assigned by this review.",
    ]
    write_markdown(output_path, lines)


def write_table_column_review_decision(
    run_dir: Path,
    decision: str = "accept",
    notes: str = "Accepted staging Layer C column geometry overlay for page 3. Geometry only; no semantic column meanings assigned.",
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    if decision not in {"accept", "reject", "needs_adjustment"}:
        raise ValueError(f"Unsupported table column review decision: {decision}")
    tables_dir = run_dir / "tables"
    columns_payload = read_json(tables_dir / "table_columns.json", {})
    validation_image = f"tables/table_columns_page-{page_number:04d}_validation.png"
    accepted_column_count = columns_payload.get("column_count", 0) if decision == "accept" else None
    payload = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "reviewed_layer": "column_reconstruction",
            "excluded_layers": ["invoice_extraction", "product_matching", "receiving_workflow", "column_semantics"],
        },
        "reviewed_artifact": validation_image,
        "decision": decision,
        "accepted_column_count": accepted_column_count,
        "notes": notes,
        "reviewer_timestamp": now_iso(),
    }
    json_path = tables_dir / "table_column_review_decisions.json"
    md_path = tables_dir / "table_column_review_decisions.md"
    write_json(json_path, payload)
    build_table_column_review_markdown(md_path, payload)
    return payload


def validate_layer_d_readiness(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    tables_dir = run_dir / "tables"
    columns_path = tables_dir / "table_columns.json"
    cells_path = tables_dir / "table_cells.json"
    review_path = tables_dir / "table_column_review_decisions.json"
    issues: List[str] = []

    columns_payload = read_json(columns_path, {})
    cells_payload = read_json(cells_path, {})
    review_payload = read_json(review_path, {})

    if not columns_path.exists():
        issues.append("missing Layer C artifact: tables/table_columns.json")
    elif columns_payload.get("status") != "ok":
        issues.append(f"table_columns.json status is {columns_payload.get('status')!r}, expected 'ok'")
    if not cells_path.exists():
        issues.append("missing Layer C artifact: tables/table_cells.json")
    elif cells_payload.get("status") != "ok":
        issues.append(f"table_cells.json status is {cells_payload.get('status')!r}, expected 'ok'")
    if not review_path.exists():
        issues.append("missing required column-geometry review artifact: tables/table_column_review_decisions.json")
    else:
        decision = review_payload.get("decision")
        if decision != "accept":
            issues.append(f"column-geometry review decision is {decision!r}; Layer D requires 'accept'")
        if review_payload.get("reviewed_artifact") != f"tables/table_columns_page-{page_number:04d}_validation.png":
            issues.append("column-geometry review did not reference the expected validation overlay")
        if decision == "accept" and review_payload.get("accepted_column_count") != columns_payload.get("column_count"):
            issues.append(
                f"accepted_column_count {review_payload.get('accepted_column_count')!r} does not match "
                f"Layer C column_count {columns_payload.get('column_count')!r}"
            )
        scope = review_payload.get("scope", {})
        if "column_semantics" not in set(scope.get("excluded_layers", [])):
            issues.append("column review scope does not explicitly exclude column semantics")

    for payload_name, payload in [("table_columns.json", columns_payload), ("table_cells.json", cells_payload)]:
        if payload and int(payload.get("page", 0)) != page_number:
            issues.append(f"{payload_name} page is {payload.get('page')!r}, expected {page_number}")
        if payload and payload.get("band_id") != band_id:
            issues.append(f"{payload_name} band_id is {payload.get('band_id')!r}, expected {band_id}")
        excluded_layers = set(payload.get("scope", {}).get("excluded_layers", []))
        if payload and not {"invoice_extraction", "product_matching", "receiving_workflow", "column_semantics"}.issubset(excluded_layers):
            issues.append(f"{payload_name} scope does not exclude semantic/business workflow layers")

    return {
        "created_at": now_iso(),
        "status": "ok" if not issues else "blocked",
        "issues": issues,
        "column_count": columns_payload.get("column_count"),
        "cell_count": cells_payload.get("cell_count"),
        "review_decision": review_payload.get("decision"),
        "reviewed_artifact": review_payload.get("reviewed_artifact"),
    }


def run_table_column_reconstruction_poc(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    readiness_path = tables_dir / "table_column_readiness.md"
    columns_json_path = tables_dir / "table_columns.json"
    columns_csv_path = tables_dir / "table_columns.csv"
    cells_json_path = tables_dir / "table_cells.json"
    cells_csv_path = tables_dir / "table_cells.csv"
    columns_summary_path = tables_dir / "table_column_summary.md"
    validation_image_path = tables_dir / f"table_columns_page-{page_number:04d}_validation.png"

    readiness = validate_layer_b_readiness(run_dir, page_number=page_number, band_id=band_id)
    build_table_column_readiness_report(readiness_path, readiness)
    if readiness["status"] != "ok":
        return {
            "created_at": now_iso(),
            "status": "blocked_by_layer_b",
            "readiness_report": str(readiness_path.relative_to(run_dir)),
            "issues": readiness["issues"],
        }

    table_bands_payload = read_json(tables_dir / "table_bands.json", {"bands": []})
    bands = table_bands_payload.get("bands", [])
    band = next((item for item in bands if item.get("band_id") == band_id and int(item.get("page", 0)) == page_number), None)
    if not band:
        payload = {
            "created_at": now_iso(),
            "status": "missing_table_band",
            "page": page_number,
            "band_id": band_id,
            "columns": [],
            "cells": [],
        }
        write_json(columns_json_path, payload)
        write_csv(columns_csv_path, [])
        write_json(cells_json_path, {"created_at": now_iso(), "status": "missing_table_band", "cells": []})
        write_csv(cells_csv_path, [])
        build_table_column_summary(columns_summary_path, payload)
        return payload

    rows = readiness["rows"]
    fused_by_id = {region.get("region_id"): region for region in readiness["fused_regions"] if region.get("region_id")}
    bx1, by1, bx2, by2 = [float(value) for value in band["bbox"]]
    band_width = max(1.0, bx2 - bx1)
    edge_tolerance = max(16.0, band_width * 0.018)

    edge_values: List[Dict[str, Any]] = []
    for row in rows:
        for region_id in row.get("source_region_ids", []):
            region = fused_by_id.get(region_id)
            if not region:
                continue
            x1, _, x2, _ = [float(value) for value in region.get("bbox", [0, 0, 0, 0])]
            if x2 < bx1 or x1 > bx2:
                continue
            edge_values.append({"x": max(bx1, min(bx2, x1)), "row_id": row["row_id"], "region_id": region_id, "edge_type": "left"})
            edge_values.append({"x": max(bx1, min(bx2, x2)), "row_id": row["row_id"], "region_id": region_id, "edge_type": "right"})

    edge_clusters = cluster_x_positions(edge_values, edge_tolerance)
    repeated_edges = [
        cluster
        for cluster in edge_clusters
        if cluster["row_support_count"] >= 2 and bx1 + edge_tolerance < cluster["x"] < bx2 - edge_tolerance
    ]
    ruling_lines = detect_column_ruling_lines(run_dir, band)
    table_edge_signals: List[Dict[str, Any]] = [
        {"x": round(bx1, 2), "source": "table_band_left", "row_ids": [], "source_region_ids": []},
        {"x": round(bx2, 2), "source": "table_band_right", "row_ids": [], "source_region_ids": []},
    ]
    ruling_signals = [
        {
            "x": line["x"],
            "source": line["source"],
            "row_ids": [],
            "source_region_ids": [],
            "support_count": line.get("support_count"),
            "longest_run": line.get("longest_run"),
        }
        for line in ruling_lines
    ]
    edge_signals = [
        {
            "x": cluster["x"],
            "source": "repeated_ocr_edge",
            "row_ids": cluster.get("row_ids", []),
            "source_region_ids": cluster.get("source_region_ids", []),
            "support_count": cluster.get("support_count"),
        }
        for cluster in repeated_edges
    ]
    primary_boundary_signals = table_edge_signals + ruling_signals
    boundary_clusters = merge_column_boundary_signals(primary_boundary_signals, tolerance=max(8.0, edge_tolerance * 0.45))
    if len(boundary_clusters) < 3:
        boundary_clusters = merge_column_boundary_signals(primary_boundary_signals + edge_signals, tolerance=max(8.0, edge_tolerance * 0.45))
    boundary_values = sorted({cluster["x"] for cluster in boundary_clusters})
    if len(boundary_values) < 3:
        row_region_centers = []
        for row in rows:
            regions = [fused_by_id.get(region_id) for region_id in row.get("source_region_ids", [])]
            for region in regions:
                if not region:
                    continue
                x1, _, x2, _ = [float(value) for value in region.get("bbox", [0, 0, 0, 0])]
                row_region_centers.append((x1 + x2) / 2.0)
        center_guess = percentile(row_region_centers, 0.5) if row_region_centers else bx1 + band_width / 2.0
        boundary_values = sorted({round(bx1, 2), round(center_guess, 2), round(bx2, 2)})
        boundary_clusters = [
            {"x": value, "sources": ["fallback_center_split"], "support_count": 1, "row_ids": [], "source_region_ids": []}
            for value in boundary_values
        ]
    boundary_by_x = {cluster["x"]: cluster for cluster in boundary_clusters}

    columns: List[Dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(boundary_values, boundary_values[1:]), 1):
        if right - left < max(8.0, band_width * 0.008):
            continue
        support_clusters = [cluster for cluster in repeated_edges if left <= cluster["x"] <= right]
        left_boundary = boundary_by_x.get(left, {"sources": ["unknown"], "row_ids": [], "source_region_ids": []})
        right_boundary = boundary_by_x.get(right, {"sources": ["unknown"], "row_ids": [], "source_region_ids": []})
        boundary_sources = sorted(set(left_boundary.get("sources", []) + right_boundary.get("sources", [])))
        row_support_count = len(
            {
                row_id
                for cluster in support_clusters
                for row_id in cluster.get("row_ids", [])
            }
        )
        ruling_bonus = 0.18 if any(source == "vertical_ruling_line" for source in boundary_sources) else 0.0
        support_ratio = row_support_count / max(1, len(rows))
        confidence = round(max(0.2, min(0.95, 0.4 + support_ratio * 0.42 + ruling_bonus)), 2)
        notes = []
        if support_ratio < 0.35:
            notes.append("sparse boundary support across Layer B rows")
        if "vertical_ruling_line" not in boundary_sources:
            notes.append("no direct vertical ruling-line support")
        columns.append(
            {
                "column_id": f"page-{page_number:04d}-column-{index:04d}",
                "page": page_number,
                "band_id": band_id,
                "column_index": index,
                "boundaries": {"left_x": round(left, 2), "right_x": round(right, 2)},
                "bbox": [int(round(left)), int(round(by1)), int(round(right)), int(round(by2))],
                "normalized_bbox": {
                    "x1": round(left / float(band["image_size"]["width"]), 6),
                    "y1": round(by1 / float(band["image_size"]["height"]), 6),
                    "x2": round(right / float(band["image_size"]["width"]), 6),
                    "y2": round(by2 / float(band["image_size"]["height"]), 6),
                },
                "stability_score": confidence,
                "confidence": confidence,
                "confidence_level": column_confidence_label(confidence),
                "boundary_sources": boundary_sources,
                "left_boundary_evidence": left_boundary,
                "right_boundary_evidence": right_boundary,
                "row_support_count": row_support_count,
                "supporting_edge_clusters": support_clusters,
                "cell_counts": {"total": 0, "empty": 0, "filled": 0, "conflicting": 0},
                "notes": notes,
            }
        )

    row_column_groups: List[Dict[str, Any]] = []
    cells: List[Dict[str, Any]] = []
    for row in rows:
        row_cells = []
        row_regions = [fused_by_id.get(region_id) for region_id in row.get("source_region_ids", [])]
        row_regions = [region for region in row_regions if region]
        for column in columns:
            cx1, _, cx2, _ = [float(value) for value in column["bbox"]]
            assigned = []
            notes = []
            for region in row_regions:
                rx1, _, rx2, _ = [float(value) for value in region.get("bbox", [0, 0, 0, 0])]
                center_x = (rx1 + rx2) / 2.0
                if cx1 <= center_x <= cx2:
                    assigned.append(region)
                    if rx1 < cx1 or rx2 > cx2:
                        notes.append(f"{region['region_id']} overlaps neighboring column boundary")
                    if rx2 > bx2:
                        notes.append(f"{region['region_id']} has overflow x coordinate beyond table band")
            cell_status = "filled" if assigned else "empty"
            has_conflict = any(region.get("classification") == "conflicting" for region in assigned)
            if has_conflict:
                cell_status = "conflicting"
            cell_id = f"{row['row_id']}-{column['column_id'].replace(f'page-{page_number:04d}-', '')}"
            cell_confidence = table_cell_confidence(assigned, column["stability_score"], notes)
            cell = {
                "cell_id": cell_id,
                "page": page_number,
                "band_id": band_id,
                "row_id": row["row_id"],
                "row_type": row.get("row_type", ""),
                "column_id": column["column_id"],
                "cell_bbox": [
                    int(round(cx1)),
                    int(round(float(row["row_bbox"][1]))),
                    int(round(cx2)),
                    int(round(float(row["row_bbox"][3]))),
                ],
                "cell_status": cell_status,
                "is_empty": not assigned,
                "has_conflict": has_conflict,
                "cell_confidence": cell_confidence,
                "source_region_ids": [region["region_id"] for region in assigned],
                "region_count": len(assigned),
                "candidate_texts_by_engine": aggregate_region_candidates_by_engine(assigned),
                "conflict_regions": [region["region_id"] for region in assigned if region.get("classification") == "conflicting"],
                "region_snapshots": [
                    {
                        "region_id": region["region_id"],
                        "bbox": region["bbox"],
                        "classification": region.get("classification"),
                        "zone": region.get("zone"),
                        "normalized_candidate_text": region.get("normalized_candidate_text"),
                        "source_engines_present": region.get("source_engines_present", []),
                    }
                    for region in assigned
                ],
                "notes": sorted(set(notes)),
            }
            cells.append(cell)
            row_cells.append(cell)
        row_column_groups.append(
            {
                "row_id": row["row_id"],
                "row_type": row.get("row_type", ""),
                "page": page_number,
                "band_id": band_id,
                "row_bbox": row["row_bbox"],
                "cells": row_cells,
            }
        )

    cells_by_column: Dict[str, List[Dict[str, Any]]] = {}
    for cell in cells:
        cells_by_column.setdefault(cell["column_id"], []).append(cell)
    for column in columns:
        column_cells = cells_by_column.get(column["column_id"], [])
        empty_count = sum(1 for cell in column_cells if cell["is_empty"])
        conflict_count = sum(1 for cell in column_cells if cell["has_conflict"])
        column["cell_counts"] = {
            "total": len(column_cells),
            "filled": len(column_cells) - empty_count,
            "empty": empty_count,
            "conflicting": conflict_count,
        }
        fill_ratio = (len(column_cells) - empty_count) / max(1, len(column_cells))
        column["stability_score"] = round(max(0.18, min(0.96, column["stability_score"] * 0.72 + fill_ratio * 0.28)), 2)
        column["confidence"] = column["stability_score"]
        column["confidence_level"] = column_confidence_label(column["stability_score"])

    missing_cells = [cell for cell in cells if cell["is_empty"]]
    conflicting_cells = [cell for cell in cells if cell["has_conflict"]]
    cells_payload = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "implemented_layers": ["column_reconstruction_cells"],
            "excluded_layers": ["invoice_extraction", "product_matching", "receiving_workflow", "column_semantics"],
        },
        "page": page_number,
        "band_id": band_id,
        "row_count": len(rows),
        "column_count": len(columns),
        "cell_count": len(cells),
        "cells": cells,
    }

    payload = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "implemented_layers": ["column_reconstruction"],
            "excluded_layers": ["invoice_extraction", "product_matching", "receiving_workflow", "column_semantics"],
        },
        "page": page_number,
        "band_id": band_id,
        "row_count": len(rows),
        "column_count": len(columns),
        "cell_count": len(cells),
        "columns": columns,
        "row_column_groups": row_column_groups,
        "boundary_evidence": {
            "edge_tolerance": round(edge_tolerance, 2),
            "repeated_edge_clusters": repeated_edges,
            "vertical_ruling_lines": ruling_lines,
            "merged_boundary_clusters": boundary_clusters,
        },
        "validation": {
            "empty_cell_count": len(missing_cells),
            "conflicting_cell_count": len(conflicting_cells),
            "missing_cells": [
                {
                    "cell_id": cell["cell_id"],
                    "row_id": cell["row_id"],
                    "column_id": cell["column_id"],
                }
                for cell in missing_cells
            ],
            "conflicting_cells": [
                {
                    "cell_id": cell["cell_id"],
                    "row_id": cell["row_id"],
                    "column_id": cell["column_id"],
                    "source_region_ids": cell["source_region_ids"],
                }
                for cell in conflicting_cells
            ],
        },
        "validation_image": str(validation_image_path.relative_to(run_dir)),
    }

    write_json(columns_json_path, payload)
    write_csv(columns_csv_path, table_column_csv_rows(columns))
    write_json(cells_json_path, cells_payload)
    write_csv(cells_csv_path, table_cell_csv_rows(cells))
    build_table_column_summary(columns_summary_path, payload)
    build_table_column_validation_image(
        run_dir / "pages" / f"page-{page_number:04d}.png",
        validation_image_path,
        band,
        columns,
        row_column_groups,
    )
    return payload


# ---------------------------------------------------------------------------
# Layer D — column semantic labeling (staging only)
# ---------------------------------------------------------------------------

LAYER_D_LABEL_VOCABULARY: frozenset = frozenset({
    "line_number",
    "product_code",
    "description",
    "unit",
    "quantity",
    "unit_price",
    "amount",
    "vat",
    "discount",
    "unknown",
})

# Ordered most-specific first to avoid substring mismatches.
# Thai patterns carry no re.IGNORECASE flag (Thai has no case); English patterns do.
_LABEL_KEYWORD_PATTERNS: List[Tuple[Any, str]] = [
    # amount — before quantity because จำนวนเงิน contains จำนวน
    (re.compile(r"จำนวนเงิน|มูลค่า"), "amount"),
    (re.compile(r"\bamount\b|\btotal\b|\bsubtotal\b|\bline\s*total\b", re.IGNORECASE), "amount"),
    # unit_price — before bare "unit" because "unit price" contains "unit"
    (re.compile(r"ราคาต่อหน่วย|ราคาต่อ|หน่วยละ"), "unit_price"),
    (re.compile(r"\bunit\s*price\b|\bunit\s*cost\b|\bprice\b|\brate\b", re.IGNORECASE), "unit_price"),
    # product_code
    (re.compile(r"รหัสสินค้า|รหัสสินค้"), "product_code"),
    (re.compile(r"\bproduct\s*code\b|\bitem\s*code\b|\bpart\s*no\.?\b|\bsku\b", re.IGNORECASE), "product_code"),
    # description
    (re.compile(r"คำอธิบาย|รายละเอียด|รายการสินค้า"), "description"),
    (re.compile(r"\bdescription\b|\bitem\s*desc(?:ription)?\b|\bproduct\s*name\b", re.IGNORECASE), "description"),
    # unit — specific Thai spellings before bare หน่วย; negative lookahead for ละ
    (re.compile(r"หน่วยนับ|หน่วยนัน"), "unit"),
    (re.compile(r"หน่วย(?!ละ|นับ|นัน)"), "unit"),
    (re.compile(r"\bunit\b", re.IGNORECASE), "unit"),
    # quantity — negative lookahead prevents matching inside จำนวนเงิน
    (re.compile(r"จำนวน(?!เงิน)"), "quantity"),
    (re.compile(r"\bqty\b|\bquantity\b|\bpcs\b|\bpieces\b", re.IGNORECASE), "quantity"),
    # vat
    (re.compile(r"ภาษีมูลค่าเพิ่ม|ภาษี"), "vat"),
    (re.compile(r"\bvat\b|\btax\b", re.IGNORECASE), "vat"),
    # discount
    (re.compile(r"ส่วนลด"), "discount"),
    (re.compile(r"\bdiscount\b|\bdisc\b", re.IGNORECASE), "discount"),
    # line_number
    (re.compile(r"ลำดับที่|ลำดับ|เลขที่"), "line_number"),
    (re.compile(r"\bno\.?\b|\bitem\s*no\.?\b|\bline\s*no\.?\b|\bseq\.?\b", re.IGNORECASE), "line_number"),
]

_BODY_INTEGER_RE = re.compile(r"^\s*\d{1,4}\s*$")
_BODY_NUMERIC_RE = re.compile(r"^\s*[\d,]+\.?\d*\s*$")
_BODY_DECIMAL_RE = re.compile(r"^\s*[\d,]+\.\d+\s*$")
_BODY_SHORT_ALPHA_RE = re.compile(r"^\s*[A-Za-z]{1,6}\s*$")
_BODY_ALNUM_CODE_RE = re.compile(r"^[A-Za-z0-9\-/]{3,20}$")
_THAI_CHAR_RE = re.compile(r"[฀-๿]")


def _is_thai_text(text: str) -> bool:
    return bool(_THAI_CHAR_RE.search(text))


def _map_text_to_label(text: str) -> Optional[str]:
    if not text or not text.strip():
        return None
    for pattern, label in _LABEL_KEYWORD_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _score_header_cell_candidates(cell: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Returns per-label evidence: {label: {engines, best_conf, has_thai, has_latin}}."""
    evidence: Dict[str, Dict[str, Any]] = {}
    for engine, candidates in cell.get("candidate_texts_by_engine", {}).items():
        for cand in candidates:
            text = cand.get("text") or ""
            conf = float(cand.get("confidence") or 0.0)
            if conf > 1.0:
                conf = conf / 100.0
            label = _map_text_to_label(text)
            if label is None:
                continue
            if label not in evidence:
                evidence[label] = {"engines": set(), "best_conf": 0.0, "has_thai": False, "has_latin": False}
            evidence[label]["engines"].add(engine)
            evidence[label]["best_conf"] = max(evidence[label]["best_conf"], conf)
            if _is_thai_text(text):
                evidence[label]["has_thai"] = True
            else:
                evidence[label]["has_latin"] = True
    return evidence


def _compute_text_label_scores(evidence: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for label, ev in evidence.items():
        engine_count = len(ev["engines"])
        best_conf = ev["best_conf"]
        score = 0.0
        if engine_count >= 2:
            score += 0.40
        elif engine_count == 1:
            score += 0.25 if best_conf >= 0.90 else 0.10
        if ev["has_thai"] and ev["has_latin"]:
            score += 0.15
        scores[label] = round(min(1.0, score), 4)
    return scores


def _body_pattern_score(body_cells: Sequence[Dict[str, Any]], candidate_label: str) -> float:
    """Score a label from body-cell content patterns. Capped at 0.20."""
    texts: List[str] = []
    for cell in body_cells:
        for candidates in cell.get("candidate_texts_by_engine", {}).values():
            for cand in candidates:
                t = (cand.get("text") or "").strip()
                if t:
                    texts.append(t)
    if not texts:
        return 0.0
    if candidate_label == "line_number":
        hits = sum(1 for t in texts if _BODY_INTEGER_RE.match(t))
    elif candidate_label in {"quantity", "amount"}:
        hits = sum(1 for t in texts if _BODY_NUMERIC_RE.match(t))
    elif candidate_label == "unit_price":
        hits = sum(1 for t in texts if _BODY_DECIMAL_RE.match(t))
    elif candidate_label == "unit":
        hits = sum(1 for t in texts if _BODY_SHORT_ALPHA_RE.match(t))
    elif candidate_label == "product_code":
        hits = sum(1 for t in texts if _BODY_ALNUM_CODE_RE.match(t))
    elif candidate_label == "description":
        hits = sum(1 for t in texts if len(t) > 8)
    else:
        return 0.0
    return round(min(0.20, (hits / len(texts)) * 0.20), 4)


def _geometric_label_prior(
    column_index: int,
    total_columns: int,
    column_width: float,
    median_width: float,
) -> Dict[str, float]:
    """Small position/width priors. Only applied when a label already has text evidence."""
    priors: Dict[str, float] = {}
    if column_index == 1:
        priors["line_number"] = 0.05
        priors["product_code"] = 0.03
    elif column_index == total_columns:
        priors["amount"] = 0.05
        priors["vat"] = 0.03
    elif column_index == total_columns - 1:
        priors["unit_price"] = 0.03
        priors["amount"] = 0.03
    width_ratio = column_width / max(1.0, median_width)
    if width_ratio >= 2.5:
        priors["description"] = priors.get("description", 0.0) + 0.05
    elif width_ratio <= 0.6:
        priors["unit"] = priors.get("unit", 0.0) + 0.03
        priors["line_number"] = priors.get("line_number", 0.0) + 0.03
    return priors


def score_column_label(
    column: Dict[str, Any],
    header_cell: Optional[Dict[str, Any]],
    body_cells: Sequence[Dict[str, Any]],
    column_index: int,
    total_columns: int,
    median_column_width: float,
) -> Dict[str, Any]:
    column_width = float(column["boundaries"]["right_x"]) - float(column["boundaries"]["left_x"])
    header_is_empty = header_cell is None or header_cell.get("is_empty", True)
    header_has_conflict = header_cell is not None and header_cell.get("has_conflict", False)

    label_scores: Dict[str, float] = {}
    evidence_signals: List[Dict[str, Any]] = []

    if not header_is_empty and header_cell is not None:
        raw_evidence = _score_header_cell_candidates(header_cell)
        raw_scores = _compute_text_label_scores(raw_evidence)
        label_scores.update(raw_scores)
        for label, ev in raw_evidence.items():
            evidence_signals.append({
                "signal_type": "header_ocr",
                "label": label,
                "engine_count": len(ev["engines"]),
                "engines": sorted(ev["engines"]),
                "best_conf": round(ev["best_conf"], 4),
                "bilingual": ev["has_thai"] and ev["has_latin"],
                "score_contribution": raw_scores.get(label, 0.0),
            })

    for candidate_label in sorted(LAYER_D_LABEL_VOCABULARY - {"unknown"}):
        body_score = _body_pattern_score(body_cells, candidate_label)
        if body_score > 0.0:
            existing = label_scores.get(candidate_label, 0.0)
            combined = existing + body_score
            if header_is_empty:
                combined = min(0.50, combined)
            else:
                combined = min(1.0, combined)
            label_scores[candidate_label] = round(combined, 4)
            evidence_signals.append({
                "signal_type": "body_pattern",
                "label": candidate_label,
                "score_contribution": body_score,
                "capped_by_body_only": header_is_empty,
            })

    priors = _geometric_label_prior(column_index, total_columns, column_width, median_column_width)
    for label, bonus in priors.items():
        if label in label_scores and label_scores[label] > 0.10:
            label_scores[label] = round(min(1.0, label_scores[label] + bonus), 4)
            evidence_signals.append({
                "signal_type": "geometric_prior",
                "label": label,
                "score_contribution": bonus,
            })

    best_label = "unknown"
    best_score = 0.0
    for label, score in label_scores.items():
        if score > best_score:
            best_score = score
            best_label = label
    if best_score < 0.30:
        best_label = "unknown"
        best_score = 0.0

    requires_review = (
        header_is_empty
        or header_has_conflict
        or best_label == "unknown"
        or best_score < 0.75
    )

    if best_score >= 0.75:
        conf_level = "high"
    elif best_score >= 0.50:
        conf_level = "medium"
    elif best_score >= 0.30:
        conf_level = "low"
    else:
        conf_level = "very_low"

    return {
        "proposed_label": best_label,
        "label_confidence": round(best_score, 4),
        "confidence_level": conf_level,
        "requires_review": requires_review,
        "header_is_empty": header_is_empty,
        "header_has_conflict": header_has_conflict,
        "evidence_signals": evidence_signals,
        "candidate_labels": {
            label: round(score, 4)
            for label, score in sorted(label_scores.items(), key=lambda x: -x[1])
        },
    }


def detect_geometry_flags(
    column: Dict[str, Any],
    candidate_labels: Dict[str, float],
    column_width: float,
    median_width: float,
    proposed_label: str,
) -> List[str]:
    """Warning-only geometry flags. Layer D never modifies geometry."""
    flags: List[str] = []
    high_scoring = [lbl for lbl, sc in candidate_labels.items() if sc >= 0.25 and lbl != "unknown"]
    if len(high_scoring) >= 2 and column_width >= 2.0 * median_width:
        flags.append("merged_header_suspected")
    if proposed_label == "description" and column_width < median_width * 0.8:
        flags.append("geometry_anomaly_suspected")
    elif proposed_label in {"quantity", "unit", "line_number", "unit_price"} and column_width > median_width * 3.0:
        flags.append("geometry_anomaly_suspected")
    return flags


def build_layer_d_readiness_markdown(output_path: Path, readiness: Dict[str, Any]) -> None:
    lines = [
        "# Layer D Readiness",
        "",
        f"Generated: {now_iso()}",
        "",
        f"- Status: `{readiness.get('status')}`",
        f"- Column count: `{readiness.get('column_count')}`",
        f"- Cell count: `{readiness.get('cell_count')}`",
        f"- Review decision: `{readiness.get('review_decision')}`",
        f"- Reviewed artifact: `{readiness.get('reviewed_artifact')}`",
        "",
        "## Gate Checks",
        "",
    ]
    issues = readiness.get("issues", [])
    if issues:
        lines.extend(f"- FAIL: {issue}" for issue in issues)
    else:
        lines.append("- All upstream gate checks passed.")
    lines.extend([
        "",
        "## Gate Decision",
        "",
        "- Layer D may run only when status is `ok`.",
        "- A blocked status means Layer D will not write semantic output.",
    ])
    write_markdown(output_path, lines)


def build_table_column_semantics_markdown(output_path: Path, payload: Dict[str, Any]) -> None:
    lines = [
        "# Table Column Semantics",
        "",
        f"Generated: {payload.get('created_at', now_iso())}",
        "",
        "- Scope: `Layer D only`",
        f"- Page: `{payload.get('page')}`",
        f"- Band ID: `{payload.get('band_id')}`",
        "",
        "## Overview",
        "",
        f"- Columns: `{payload.get('column_count')}`",
        f"- Review-required columns: `{len(payload.get('review_required_columns', []))}`",
        f"- Geometry flags present: `{payload.get('geometry_flags_present')}`",
        "",
        "## Proposed Labels",
        "",
    ]
    for col in payload.get("columns", []):
        label = col["proposed_label"]
        conf = col["label_confidence"]
        conf_level = col["confidence_level"]
        geo_flags = col.get("geometry_flags", [])
        flag_str = f"  **FLAGS: {', '.join(geo_flags)}**" if geo_flags else ""
        review_str = "  *(requires human review)*" if col["requires_review"] else ""
        lines.append(
            f"- `{col['column_id']}` → `{label}` confidence `{conf}` ({conf_level}){review_str}{flag_str}"
        )
    lines.extend(["", "## Column Detail", ""])
    for col in payload.get("columns", []):
        lines.extend([
            f"### {col['column_id']}",
            "",
            f"- Proposed label: `{col['proposed_label']}`",
            f"- Confidence: `{col['label_confidence']}` ({col['confidence_level']})",
            f"- Requires review: `{col['requires_review']}`",
            f"- Header empty: `{col['header_is_empty']}`",
            f"- Header conflicting: `{col['header_has_conflict']}`",
        ])
        candidate_labels = col.get("candidate_labels", {})
        if candidate_labels:
            lines.extend(["", "**Candidate labels (scored):**", ""])
            for clabel, cscore in candidate_labels.items():
                lines.append(f"  - `{clabel}`: `{cscore}`")
        geo_flags = col.get("geometry_flags", [])
        if geo_flags:
            lines.extend(["", "**Geometry flags (warning only — geometry not modified):**", ""])
            for flag in geo_flags:
                lines.append(f"  - `{flag}`")
        notes = col.get("notes", [])
        if notes:
            lines.extend(["", "**Notes:**", ""])
            for note in notes:
                lines.append(f"  - {note}")
        lines.append("")
    lines.extend([
        "## Scope Notes",
        "",
        "- Layer D proposes semantic labels only. No geometry modification.",
        "- Layer D does not perform invoice extraction, product matching, or receiving workflow.",
        "- Geometry flags are human-review warnings only. Geometry is owned by Layer C.",
        f"- Label vocabulary: {', '.join(f'`{v}`' for v in sorted(payload.get('label_vocabulary', [])))}",
        "",
        "## Review Gate",
        "",
        "- This document is the reviewed artifact for the Layer D human review gate.",
        "- Review gate artifact: `tables/table_column_semantics_review_decisions.json`",
        "- Downstream layers require `decision` in `[accept, accept_with_adjustments]`.",
    ])
    write_markdown(output_path, lines)


def run_table_column_semantics_poc(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    readiness_path = tables_dir / "layer_d_readiness.md"
    semantics_json_path = tables_dir / "table_column_semantics.json"
    semantics_md_path = tables_dir / "table_column_semantics.md"

    readiness = validate_layer_d_readiness(run_dir, page_number=page_number, band_id=band_id)
    build_layer_d_readiness_markdown(readiness_path, readiness)

    if readiness["status"] != "ok":
        return {
            "created_at": now_iso(),
            "status": "blocked",
            "readiness_report": str(readiness_path.relative_to(run_dir)),
            "issues": readiness["issues"],
        }

    columns_payload = read_json(tables_dir / "table_columns.json", {})
    cells_payload = read_json(tables_dir / "table_cells.json", {})
    columns = columns_payload.get("columns", [])
    cells = cells_payload.get("cells", [])

    header_cell_by_column: Dict[str, Optional[Dict[str, Any]]] = {}
    body_cells_by_column: Dict[str, List[Dict[str, Any]]] = {}
    for cell in cells:
        col_id = cell.get("column_id", "")
        if cell.get("row_type") == "header":
            header_cell_by_column[col_id] = cell
        else:
            body_cells_by_column.setdefault(col_id, []).append(cell)

    column_widths = [
        float(col["boundaries"]["right_x"]) - float(col["boundaries"]["left_x"])
        for col in columns
    ]
    median_width = percentile(column_widths, 0.5) if column_widths else 1.0
    total_columns = len(columns)

    semantics_columns: List[Dict[str, Any]] = []
    requires_review_ids: List[str] = []
    geometry_flags_present = False

    for column in columns:
        col_id = column["column_id"]
        col_index = column["column_index"]
        col_width = float(column["boundaries"]["right_x"]) - float(column["boundaries"]["left_x"])
        header_cell = header_cell_by_column.get(col_id)
        body_cells = body_cells_by_column.get(col_id, [])

        result = score_column_label(
            column=column,
            header_cell=header_cell,
            body_cells=body_cells,
            column_index=col_index,
            total_columns=total_columns,
            median_column_width=median_width,
        )
        geo_flags = detect_geometry_flags(
            column=column,
            candidate_labels=result["candidate_labels"],
            column_width=col_width,
            median_width=median_width,
            proposed_label=result["proposed_label"],
        )
        if geo_flags:
            geometry_flags_present = True

        notes: List[str] = [
            f"{flag}: geometry concern flagged for human review; Layer D does not modify geometry"
            for flag in geo_flags
        ]
        col_entry: Dict[str, Any] = {
            "column_id": col_id,
            "column_index": col_index,
            "boundaries": column["boundaries"],
            "proposed_label": result["proposed_label"],
            "label_confidence": result["label_confidence"],
            "confidence_level": result["confidence_level"],
            "requires_review": result["requires_review"],
            "header_is_empty": result["header_is_empty"],
            "header_has_conflict": result["header_has_conflict"],
            "evidence_signals": result["evidence_signals"],
            "candidate_labels": result["candidate_labels"],
            "geometry_flags": geo_flags,
            "notes": notes,
        }
        if result["requires_review"]:
            requires_review_ids.append(col_id)
        semantics_columns.append(col_entry)

    payload: Dict[str, Any] = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "implemented_layers": ["column_semantics"],
            "excluded_layers": [
                "invoice_extraction",
                "product_matching",
                "receiving_workflow",
                "geometry_modification",
            ],
        },
        "page": page_number,
        "band_id": band_id,
        "column_count": len(columns),
        "label_vocabulary": sorted(LAYER_D_LABEL_VOCABULARY),
        "columns": semantics_columns,
        "review_required_columns": requires_review_ids,
        "geometry_flags_present": geometry_flags_present,
        "upstream_gate": {
            "layer_b_ok": True,
            "layer_c_ok": True,
            "column_review_decision": readiness.get("review_decision"),
        },
    }

    write_json(semantics_json_path, payload)
    build_table_column_semantics_markdown(semantics_md_path, payload)
    return payload


# ---------------------------------------------------------------------------
# Layer D review gate — semantic label acceptance
# ---------------------------------------------------------------------------

_DEFAULT_SEMANTICS_REVIEW_NOTES: List[str] = [
    "All 7 columns require review.",
    "Column 2 has merged_header_suspected warning but remains single-column description under current Layer C geometry.",
    "Columns 1, 6, and 7 remain unknown and must block value extraction for those fields later.",
    "No product matching, invoice extraction, receiving workflow, or stock update is approved.",
]


def build_table_column_semantics_review_markdown(output_path: Path, payload: Dict[str, Any]) -> None:
    decision = payload.get("decision", "")
    accepted_labels = payload.get("accepted_labels", {})
    notes = payload.get("notes", [])
    if isinstance(notes, str):
        notes = [notes]
    lines = [
        "# Table Column Semantics Review Decisions",
        "",
        f"Generated: {payload.get('created_at', now_iso())}",
        "",
        "## Layer D Semantic Label Review",
        "",
        f"- Reviewed artifact: `{payload.get('reviewed_artifact')}`",
        f"- Decision: `{decision}`",
        f"- Reviewer timestamp: `{payload.get('reviewer_timestamp')}`",
        "",
        "## Accepted Labels",
        "",
    ]
    if accepted_labels:
        for col_id, label in accepted_labels.items():
            lines.append(f"- `{col_id}`: `{label}`")
    else:
        lines.append("- No labels accepted (decision is not accept or accept_with_adjustments).")
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
    lines.extend([
        "",
        "## Scope",
        "",
        "- Semantic label acceptance only.",
        "- No invoice extraction, product matching, receiving workflow, or stock update is approved by this review.",
        "- Columns with `unknown` label must block downstream value extraction unless explicitly allowed later.",
    ])
    write_markdown(output_path, lines)


def write_table_column_semantics_review_decision(
    run_dir: Path,
    decision: str = "accept_with_adjustments",
    notes: Optional[List[str]] = None,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    valid_decisions = {"accept", "accept_with_adjustments", "reject", "needs_more_evidence"}
    if decision not in valid_decisions:
        raise ValueError(
            f"Unsupported semantic review decision: {decision!r}. Must be one of {sorted(valid_decisions)}"
        )
    if notes is None:
        notes = _DEFAULT_SEMANTICS_REVIEW_NOTES

    tables_dir = run_dir / "tables"
    semantics_payload = read_json(tables_dir / "table_column_semantics.json", {})

    accepted_labels: Dict[str, str] = {}
    if decision in {"accept", "accept_with_adjustments"}:
        for col in semantics_payload.get("columns", []):
            accepted_labels[col["column_id"]] = col.get("proposed_label", "unknown")

    payload: Dict[str, Any] = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "reviewed_layer": "column_semantics",
            "excluded_layers": [
                "invoice_extraction",
                "product_matching",
                "receiving_workflow",
                "geometry_modification",
            ],
        },
        "reviewed_artifact": "tables/table_column_semantics.md",
        "decision": decision,
        "accepted_labels": accepted_labels,
        "notes": notes,
        "reviewer_timestamp": now_iso(),
    }

    json_path = tables_dir / "table_column_semantics_review_decisions.json"
    md_path = tables_dir / "table_column_semantics_review_decisions.md"
    write_json(json_path, payload)
    build_table_column_semantics_review_markdown(md_path, payload)
    return payload


# ---------------------------------------------------------------------------
# Layer E readiness gate (Layer E is not yet implemented)
# ---------------------------------------------------------------------------

def validate_layer_e_readiness(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    layer_d = validate_layer_d_readiness(run_dir, page_number=page_number, band_id=band_id)
    issues: List[str] = list(layer_d.get("issues", []))
    warnings: List[str] = []

    tables_dir = run_dir / "tables"
    semantics_path = tables_dir / "table_column_semantics.json"
    semantics_review_path = tables_dir / "table_column_semantics_review_decisions.json"

    semantics_payload = read_json(semantics_path, {})
    review_payload = read_json(semantics_review_path, {})

    if not semantics_path.exists():
        issues.append("missing Layer D artifact: tables/table_column_semantics.json")
    elif semantics_payload.get("status") != "ok":
        issues.append(f"table_column_semantics.json status is {semantics_payload.get('status')!r}, expected 'ok'")

    if not semantics_review_path.exists():
        issues.append(
            "missing Layer D semantic review artifact: tables/table_column_semantics_review_decisions.json"
        )
    else:
        decision = review_payload.get("decision")
        if decision not in {"accept", "accept_with_adjustments"}:
            issues.append(
                f"semantic review decision is {decision!r}; "
                "Layer E requires 'accept' or 'accept_with_adjustments'"
            )
        reviewed_artifact = review_payload.get("reviewed_artifact")
        if reviewed_artifact != "tables/table_column_semantics.md":
            issues.append(
                f"semantic review reviewed_artifact is {reviewed_artifact!r}, "
                "expected 'tables/table_column_semantics.md'"
            )
        accepted_labels = review_payload.get("accepted_labels", {})
        if decision in {"accept", "accept_with_adjustments"}:
            if not accepted_labels:
                issues.append("semantic review accepted_labels is empty for an accept decision")
            semantics_col_count = semantics_payload.get("column_count", 0)
            if accepted_labels and len(accepted_labels) != semantics_col_count:
                issues.append(
                    f"accepted_labels has {len(accepted_labels)} entries but "
                    f"Layer D column_count is {semantics_col_count}"
                )
            for col_id, label in accepted_labels.items():
                if label not in LAYER_D_LABEL_VOCABULARY:
                    issues.append(
                        f"accepted label {label!r} for {col_id} is outside the Layer D vocabulary"
                    )
        scope = review_payload.get("scope", {})
        required_excluded = {"invoice_extraction", "product_matching", "receiving_workflow"}
        if not required_excluded.issubset(set(scope.get("excluded_layers", []))):
            issues.append(
                "semantic review scope does not explicitly exclude extraction/business layers"
            )

    accepted_labels_out = review_payload.get("accepted_labels", {})
    unknown_columns = [col_id for col_id, label in accepted_labels_out.items() if label == "unknown"]
    for col_id in unknown_columns:
        warnings.append(
            f"{col_id} has label 'unknown': downstream value extraction for this column is blocked "
            "until an explicit allow decision is recorded"
        )

    if issues:
        status = "blocked"
    elif unknown_columns:
        status = "partial"
    else:
        status = "ok"

    return {
        "created_at": now_iso(),
        "status": status,
        "issues": issues,
        "warnings": warnings,
        "semantic_review_decision": review_payload.get("decision") if review_payload else None,
        "accepted_labels": accepted_labels_out,
        "unknown_columns": unknown_columns,
        "column_count": semantics_payload.get("column_count") if semantics_payload else None,
        "layer_d_readiness_status": layer_d.get("status"),
    }


def build_layer_e_readiness_markdown(output_path: Path, readiness: Dict[str, Any]) -> None:
    lines = [
        "# Layer E Readiness",
        "",
        f"Generated: {now_iso()}",
        "",
        f"- Status: `{readiness.get('status')}`",
        f"- Semantic review decision: `{readiness.get('semantic_review_decision')}`",
        f"- Column count: `{readiness.get('column_count')}`",
        f"- Unknown columns: `{len(readiness.get('unknown_columns', []))}`",
        "",
        "## Gate Checks",
        "",
    ]
    issues = readiness.get("issues", [])
    if issues:
        lines.extend(f"- FAIL: {issue}" for issue in issues)
    else:
        lines.append("- All upstream gate checks passed.")
    warnings = readiness.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- WARN: {w}" for w in warnings)
    accepted = readiness.get("accepted_labels", {})
    if accepted:
        lines.extend(["", "## Accepted Labels", ""])
        for col_id, label in accepted.items():
            lines.append(f"- `{col_id}`: `{label}`")
    lines.extend([
        "",
        "## Gate Decision",
        "",
        "- `ok` — all gates passed and all accepted labels are known. Full extraction may be designed.",
        "- `partial` — all gates passed but one or more accepted labels are `unknown`. "
        "Layer E may not perform full extraction. Future extraction must either explicitly support "
        "partial extraction or require a separate `allow_partial_extraction` flag.",
        "- `blocked` — hard gate failure. Layer E must not run.",
        "",
        "- Layer E is NOT yet implemented. This gate confirms readiness only.",
        "- Columns with `unknown` label block their own value extraction until an explicit allow decision.",
        "- No invoice extraction, product matching, receiving workflow, or stock update is permitted "
        "in Layer E without additional design and review.",
    ])
    write_markdown(output_path, lines)


# ---------------------------------------------------------------------------
# Layer E-0 — row classification (staging only)
# ---------------------------------------------------------------------------

LAYER_E0_ROW_CLASSES: frozenset = frozenset({
    "header",
    "product_line",
    "continuation_row",
    "subtotal_row",
    "total_row",
    "footer_row",
    "unknown_row",
})

_SUBTOTAL_KEYWORD_RE = re.compile(
    r"รวม|ยอดรวม|subtotal|sub\s*total|รวมทั้งหมด", re.IGNORECASE
)
_TOTAL_KEYWORD_RE = re.compile(
    r"grand\s*total|รวมทั้งสิ้น|ยอดสุทธิ|net\s*total|total\s*amount", re.IGNORECASE
)
_CLF_NUMERIC_RE = re.compile(r"^\s*[\d,]+\.?\d*\s*$")


def _row_bboxes_overlap_vertically(bbox_a: Sequence[float], bbox_b: Sequence[float]) -> bool:
    _, ay1, _, ay2 = [float(v) for v in bbox_a]
    _, by1, _, by2 = [float(v) for v in bbox_b]
    return ay1 <= by2 and by1 <= ay2


def _row_has_split_note(row: Dict[str, Any]) -> bool:
    return any("possible split" in note.lower() for note in row.get("notes", []))


def _cell_best_text(cell: Dict[str, Any]) -> str:
    best_text, best_conf = "", -1.0
    for candidates in cell.get("candidate_texts_by_engine", {}).values():
        for cand in candidates:
            conf = float(cand.get("confidence") or 0.0)
            if conf > 1.0:
                conf /= 100.0
            if conf > best_conf:
                best_conf = conf
                best_text = (cand.get("text") or "").strip()
    return best_text


def _compute_row_signals(
    row: Dict[str, Any],
    cells_for_row: List[Dict[str, Any]],
    accepted_labels: Dict[str, str],
    prev_row_bbox: Optional[Sequence[float]],
    prev_row_class: Optional[str],
) -> Dict[str, Any]:
    description_col_id = next(
        (c for c, lbl in accepted_labels.items() if lbl == "description"), None
    )
    numeric_col_ids = {
        c for c, lbl in accepted_labels.items()
        if lbl in {"quantity", "unit_price", "amount", "vat", "discount"}
    }
    known_col_ids = {c for c, lbl in accepted_labels.items() if lbl != "unknown"}

    label_term_count = 0
    label_terms_in_cells: Dict[str, str] = {}
    known_label_fill_count = 0
    numeric_fill_count = 0
    description_is_label_term = False
    all_numeric_cols_empty = True
    conflict_count = sum(1 for c in cells_for_row if c.get("has_conflict"))

    for cell in cells_for_row:
        col_id = cell.get("column_id", "")
        is_empty = cell.get("is_empty", True)

        # Label-term detection: one count per cell (first engine match wins)
        cell_label_hit: Optional[str] = None
        for engine_candidates in cell.get("candidate_texts_by_engine", {}).values():
            if cell_label_hit is not None:
                break
            for cand in engine_candidates:
                hit = _map_text_to_label((cand.get("text") or "").strip())
                if hit is not None:
                    cell_label_hit = hit
                    break
        if cell_label_hit is not None:
            label_term_count += 1
            label_terms_in_cells[col_id] = cell_label_hit
            if col_id == description_col_id:
                description_is_label_term = True

        # Numeric detection: use best-confidence text
        best = _cell_best_text(cell)
        if _CLF_NUMERIC_RE.match(best):
            numeric_fill_count += 1
            if col_id in numeric_col_ids:
                all_numeric_cols_empty = False

        # Known-label fill count
        if col_id in known_col_ids and not is_empty:
            known_label_fill_count += 1

    # Description cell text for subtotal/total keyword detection
    description_text = ""
    if description_col_id:
        desc_cell = next(
            (c for c in cells_for_row if c.get("column_id") == description_col_id), None
        )
        if desc_cell:
            description_text = _cell_best_text(desc_cell)

    row_bbox = row.get("row_bbox") or []
    bbox_overlap = (
        len(row_bbox) == 4
        and prev_row_bbox is not None
        and len(prev_row_bbox) == 4
        and _row_bboxes_overlap_vertically(prev_row_bbox, row_bbox)
    )

    return {
        "label_term_count": label_term_count,
        "label_terms_in_cells": label_terms_in_cells,
        "known_label_fill_count": known_label_fill_count,
        "numeric_fill_count": numeric_fill_count,
        "description_is_label_term": description_is_label_term,
        "all_numeric_cols_empty": all_numeric_cols_empty,
        "row_conflict_count": conflict_count,
        "possible_split_flag": _row_has_split_note(row),
        "bbox_overlap_with_prev": bbox_overlap,
        "prev_row_class": prev_row_class,
        "description_text": description_text,
        "is_subtotal_keyword": bool(_SUBTOTAL_KEYWORD_RE.search(description_text)) if description_text else False,
        "is_total_keyword": bool(_TOTAL_KEYWORD_RE.search(description_text)) if description_text else False,
        "total_known_labels": len(known_col_ids),
        "total_numeric_cols": len(numeric_col_ids),
    }


def _classify_from_signals(
    signals: Dict[str, Any],
    row_index: int,
    total_body_rows: int,
) -> Tuple[str, float, bool, List[str]]:
    ltc = signals["label_term_count"]
    known_fill = signals["known_label_fill_count"]
    numeric_fill = signals["numeric_fill_count"]
    desc_is_label = signals["description_is_label_term"]
    all_num_empty = signals["all_numeric_cols_empty"]
    conflict_count = signals["row_conflict_count"]
    possible_split = signals["possible_split_flag"]
    bbox_overlap = signals["bbox_overlap_with_prev"]
    prev_class = signals.get("prev_row_class")
    total_known = max(1, signals["total_known_labels"])
    total_numeric = max(1, signals["total_numeric_cols"])
    notes: List[str] = []

    # Rule F1: strong footer — label saturation with no numeric content in known numeric cols
    if ltc >= 3 and all_num_empty:
        conf = round(
            min(1.0, 0.50 + (ltc / max(1, total_known)) * 0.35 + (0.15 if desc_is_label else 0.0)),
            4,
        )
        if desc_is_label:
            notes.append("description cell contains a column-label vocabulary term")
        notes.append(
            f"label_term_count={ltc} with no numeric content in known numeric-labeled columns"
        )
        return "footer_row", conf, conflict_count > 0, notes

    # Rule F2: description cell is label term, no numeric content, sparse fill
    if desc_is_label and all_num_empty and known_fill <= 2:
        notes.append("description cell is a label vocabulary term; no numeric content in row")
        return "footer_row", 0.65, True, notes

    # Rule C1: continuation — previous was product/continuation AND bbox overlap or split note
    if prev_class in {"product_line", "continuation_row"} and (bbox_overlap or possible_split):
        conf = round(
            0.55 + (0.15 if bbox_overlap else 0.0) + (0.10 if possible_split else 0.0), 4
        )
        notes.append(
            "bbox_overlap_or_split_note detected adjacent to product_line or continuation_row"
        )
        if ltc >= 2:
            notes.append(
                f"label_term_contamination_count={ltc}: low-confidence engines likely reading "
                "header text from adjacent region boundary"
            )
        return "continuation_row", conf, True, notes

    # Rule U1: label terms AND numeric content — genuinely ambiguous
    if ltc >= 2 and not all_num_empty:
        notes.append(
            f"label_term_count={ltc} conflicts with numeric content in row: "
            "cannot resolve without human review"
        )
        return "unknown_row", 0.0, True, notes

    # Rule T1: total keyword in description, last body row
    if signals["is_total_keyword"] and row_index == total_body_rows - 1:
        notes.append("total keyword detected in description cell; row is last in table body")
        return "total_row", 0.70, True, notes

    # Rule S1: subtotal keyword in description
    if signals["is_subtotal_keyword"]:
        notes.append("subtotal keyword detected in description cell")
        return "subtotal_row", 0.70, True, notes

    # Rule P1: product line — known columns filled, numeric evidence present.
    # ltc <= 1 tolerates one noisy label-term hit (e.g. "NO" inside a product code like "-D12-NO}")
    if known_fill >= 2 and ltc <= 1 and numeric_fill >= 1:
        known_score = (known_fill / total_known) * 0.40
        numeric_score = min(1.0, numeric_fill / total_numeric) * 0.30
        conflict_penalty = min(0.20, conflict_count * 0.05)
        conf = round(max(0.0, known_score + numeric_score + 0.30 - conflict_penalty), 4)
        requires = conf < 0.75 or conflict_count > 0 or possible_split
        if ltc == 1:
            notes.append(
                "label_term_noise_tolerance: one label-term hit present but treated as OCR noise "
                "(e.g. substring match inside a product code); requires human review"
            )
            requires = True
        if possible_split:
            notes.append("possible_split_note: may be part of a multi-line product entry")
        return "product_line", conf, requires, notes

    # Rule P2: product line — weak evidence (no numeric but known cols filled)
    if known_fill >= 1 and ltc == 0:
        conf = round((known_fill / total_known) * 0.35, 4)
        notes.append("weak product signal: known columns filled but numeric evidence absent")
        return "product_line", conf, True, notes

    notes.append("no classification rule matched")
    return "unknown_row", 0.0, True, notes


def build_row_classification_markdown(output_path: Path, payload: Dict[str, Any]) -> None:
    summary = payload.get("classification_summary", {})
    rows = payload.get("rows", [])
    lines = [
        "# Table Row Classification",
        "",
        f"Generated: {payload.get('created_at', now_iso())}",
        "",
        "- Scope: `Layer E-0 only`",
        f"- Page: `{payload.get('page')}`",
        f"- Band ID: `{payload.get('band_id')}`",
        "",
        "## Overview",
        "",
        f"- Total rows: `{payload.get('row_count')}`",
    ]
    for cls in sorted(LAYER_E0_ROW_CLASSES):
        count = summary.get(cls, 0)
        if count:
            lines.append(f"- {cls}: `{count}`")
    lines.append(f"- Requires review: `{payload.get('requires_review_count', 0)}`")
    lines.extend(["", "## Row Classifications", ""])
    for row in rows:
        conf = row["classification_confidence"]
        review_str = "  *(requires human review)*" if row["requires_review"] else ""
        lines.append(
            f"- `{row['row_id']}` → `{row['classification']}` confidence `{conf}`{review_str}"
        )
    lines.extend(["", "## Row Detail", ""])
    for row in rows:
        lines.extend([
            f"### {row['row_id']}",
            "",
            f"- Classification: `{row['classification']}`",
            f"- Confidence: `{row['classification_confidence']}`",
            f"- Requires review: `{row['requires_review']}`",
            f"- Row type from Layer B: `{row.get('row_type_from_layer_b')}`",
        ])
        label_terms = row.get("label_terms_in_cells", {})
        if label_terms:
            lines.extend(["", "**Label terms detected in cells:**", ""])
            for col_id, term in label_terms.items():
                lines.append(f"  - `{col_id}`: mapped to `{term}`")
        sigs = row.get("signals", {})
        if sigs:
            lines.extend(["", "**Signals:**", ""])
            for k, v in sigs.items():
                lines.append(f"  - `{k}`: `{v}`")
        row_notes = row.get("notes", [])
        if row_notes:
            lines.extend(["", "**Notes:**", ""])
            for note in row_notes:
                lines.append(f"  - {note}")
        lines.append("")
    lines.extend([
        "## Scope Notes",
        "",
        "- Layer E-0 classifies rows only. No value extraction.",
        "- No product matching, invoice extraction, geometry modification, or receiving workflow.",
        "- All Layer A/B/C/D artifacts are read-only.",
        "",
        "## Review Gate",
        "",
        "- This document is the reviewed artifact for the Layer E-0 classification review gate.",
        "- Review gate artifact: `tables/table_row_classification_review_decisions.json`",
        "- Layer E value extraction requires this gate to pass.",
    ])
    write_markdown(output_path, lines)


def build_row_classification_review_markdown(output_path: Path, payload: Dict[str, Any]) -> None:
    decisions = payload.get("decisions", [])
    lines = [
        "# Table Row Classification Review Decisions",
        "",
        f"Generated: {payload.get('created_at', now_iso())}",
        "",
        "## Row Classification Review",
        "",
        f"- Reviewed artifact: `{payload.get('reviewed_artifact')}`",
        f"- Decision: `{payload.get('decision')}`",
        f"- Reviewer timestamp: `{payload.get('reviewer_timestamp')}`",
        "",
        "## Per-Row Decisions",
        "",
    ]
    for d in decisions:
        proposed = d.get("proposed_class", "")
        confirmed = d.get("confirmed_class", "")
        dec = d.get("decision", "")
        override_str = f" *(overrides proposed `{proposed}`)*" if dec == "override" and confirmed != proposed else ""
        lines.append(f"- `{d.get('row_id', '')}`: `{dec}` → `{confirmed}`{override_str}")
    notes = payload.get("notes", [])
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
    lines.extend([
        "",
        "## Scope",
        "",
        "- Row classification acceptance only. No value extraction approved by this review.",
        "- No product matching, invoice extraction, receiving workflow, or stock update approved.",
    ])
    write_markdown(output_path, lines)


def write_row_classification_review_decision(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if notes is None:
        notes = []
    tables_dir = run_dir / "tables"
    clf_payload = read_json(tables_dir / "table_row_classification.json", {})
    decisions = [
        {
            "row_id": row["row_id"],
            "decision": "confirm",
            "proposed_class": row["classification"],
            "confirmed_class": row["classification"],
        }
        for row in clf_payload.get("rows", [])
    ]
    payload: Dict[str, Any] = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "reviewed_layer": "row_classification",
            "excluded_layers": [
                "invoice_extraction",
                "product_matching",
                "receiving_workflow",
                "geometry_modification",
            ],
        },
        "reviewed_artifact": "tables/table_row_classification.md",
        "decision": "accept",
        "decisions": decisions,
        "notes": notes,
        "reviewer_timestamp": now_iso(),
    }
    json_path = tables_dir / "table_row_classification_review_decisions.json"
    md_path = tables_dir / "table_row_classification_review_decisions.md"
    write_json(json_path, payload)
    build_row_classification_review_markdown(md_path, payload)
    return payload


def run_row_classification_poc(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    json_path = tables_dir / "table_row_classification.json"
    md_path = tables_dir / "table_row_classification.md"

    layer_e = validate_layer_e_readiness(run_dir, page_number=page_number, band_id=band_id)
    if layer_e["status"] == "blocked":
        return {
            "created_at": now_iso(),
            "status": "blocked_by_layer_e_gate",
            "issues": layer_e["issues"],
        }

    rows_payload = read_json(tables_dir / "table_rows.json", {})
    cells_payload = read_json(tables_dir / "table_cells.json", {})
    review_payload = read_json(tables_dir / "table_column_semantics_review_decisions.json", {})

    rows = rows_payload.get("rows", [])
    cells = cells_payload.get("cells", [])
    accepted_labels: Dict[str, str] = review_payload.get("accepted_labels", {})

    cells_by_row: Dict[str, List[Dict[str, Any]]] = {}
    for cell in cells:
        cells_by_row.setdefault(cell.get("row_id", ""), []).append(cell)

    body_rows = [r for r in rows if r.get("row_type") != "header"]
    summary: Dict[str, int] = {cls: 0 for cls in LAYER_E0_ROW_CLASSES}
    classified_rows: List[Dict[str, Any]] = []
    requires_review_count = 0
    prev_bbox: Optional[List[float]] = None
    prev_class: Optional[str] = None

    for row in rows:
        row_id = row.get("row_id", "")
        row_type_b = row.get("row_type", "body")

        if row_type_b == "header":
            entry: Dict[str, Any] = {
                "row_id": row_id,
                "row_type_from_layer_b": "header",
                "classification": "header",
                "classification_confidence": 1.0,
                "requires_review": False,
                "signals": {},
                "label_terms_in_cells": {},
                "notes": ["header row assigned by Layer B; not re-classified"],
            }
            summary["header"] += 1
            classified_rows.append(entry)
            prev_bbox = row.get("row_bbox")
            prev_class = "header"
            continue

        row_cells = cells_by_row.get(row_id, [])
        body_index = next(
            (i for i, r in enumerate(body_rows) if r.get("row_id") == row_id), 0
        )
        signals = _compute_row_signals(
            row, row_cells, accepted_labels, prev_bbox, prev_class
        )
        classification, confidence, requires_review, clf_notes = _classify_from_signals(
            signals, body_index, len(body_rows)
        )

        entry = {
            "row_id": row_id,
            "row_type_from_layer_b": row_type_b,
            "classification": classification,
            "classification_confidence": confidence,
            "requires_review": requires_review,
            "signals": {
                k: v for k, v in signals.items()
                if k not in {"description_text", "label_terms_in_cells"}
            },
            "label_terms_in_cells": signals["label_terms_in_cells"],
            "notes": clf_notes,
        }
        summary[classification] = summary.get(classification, 0) + 1
        if requires_review:
            requires_review_count += 1
        classified_rows.append(entry)
        prev_bbox = row.get("row_bbox")
        prev_class = classification

    payload: Dict[str, Any] = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "implemented_layers": ["row_classification"],
            "excluded_layers": [
                "invoice_extraction",
                "product_matching",
                "receiving_workflow",
                "geometry_modification",
            ],
        },
        "page": page_number,
        "band_id": band_id,
        "row_count": len(rows),
        "allowed_classes": sorted(LAYER_E0_ROW_CLASSES),
        "classification_summary": summary,
        "requires_review_count": requires_review_count,
        "rows": classified_rows,
        "layer_e_gate_status": layer_e["status"],
    }

    write_json(json_path, payload)
    build_row_classification_markdown(md_path, payload)
    return payload


# ---------------------------------------------------------------------------
# Layer E — partial extraction (staging only)
# ---------------------------------------------------------------------------

_DEFAULT_ALLOW_PARTIAL_NOTES: List[str] = [
    "Partial extraction is allowed only for identifying product description, unit, quantity, and unit_price.",
    "Unknown amount/VAT/total columns are excluded.",
    "No invoice total validation is approved.",
    "No product matching or stock update is approved.",
]


def build_allow_partial_extraction_markdown(output_path: Path, payload: Dict[str, Any]) -> None:
    lines = [
        "# Allow Partial Extraction",
        "",
        f"Generated: {payload.get('created_at', now_iso())}",
        "",
        f"- Decision: `{payload.get('decision')}`",
        f"- Extraction mode: `{payload.get('extraction_mode')}`",
        f"- Reviewer timestamp: `{payload.get('reviewer_timestamp')}`",
        "",
        "## Allowed Known Labels",
        "",
    ]
    for lbl in payload.get("allowed_known_labels", []):
        lines.append(f"- `{lbl}`")
    lines.extend(["", "## Excluded Unknown Columns", ""])
    for col_id in payload.get("excluded_unknown_columns", []):
        lines.append(f"- `{col_id}`")
    notes = payload.get("notes", [])
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
    lines.extend([
        "",
        "## Scope",
        "",
        "- This gate permits partial extraction only.",
        "- Unknown columns remain excluded and cell-preserved.",
        "- No product matching, stock update, or receiving workflow is permitted.",
    ])
    write_markdown(output_path, lines)


def write_allow_partial_extraction(
    run_dir: Path,
    decision: str = "allow",
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    valid = {"allow", "deny"}
    if decision not in valid:
        raise ValueError(f"allow_partial_extraction decision must be one of {sorted(valid)}, got {decision!r}")
    if notes is None:
        notes = _DEFAULT_ALLOW_PARTIAL_NOTES

    tables_dir = run_dir / "tables"
    sem_review = read_json(tables_dir / "table_column_semantics_review_decisions.json", {})
    accepted_labels: Dict[str, str] = sem_review.get("accepted_labels", {})

    allowed_known_labels = sorted({lbl for lbl in accepted_labels.values() if lbl != "unknown"})
    excluded_unknown_columns = [col_id for col_id, lbl in accepted_labels.items() if lbl == "unknown"]

    payload: Dict[str, Any] = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "excluded_layers": [
                "invoice_extraction", "product_matching",
                "receiving_workflow", "sku_lookup", "stock_update",
            ],
        },
        "decision": decision,
        "extraction_mode": "partial",
        "allowed_known_labels": allowed_known_labels,
        "excluded_unknown_columns": excluded_unknown_columns,
        "notes": notes,
        "reviewer_timestamp": now_iso(),
    }
    json_path = tables_dir / "allow_partial_extraction.json"
    md_path = tables_dir / "allow_partial_extraction.md"
    write_json(json_path, payload)
    build_allow_partial_extraction_markdown(md_path, payload)
    return payload


def validate_layer_e_partial_readiness(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    layer_e = validate_layer_e_readiness(run_dir, page_number=page_number, band_id=band_id)
    issues: List[str] = list(layer_e.get("issues", []))

    tables_dir = run_dir / "tables"
    allow_path = tables_dir / "allow_partial_extraction.json"
    clf_review_path = tables_dir / "table_row_classification_review_decisions.json"
    clf_path = tables_dir / "table_row_classification.json"

    allow_payload = read_json(allow_path, {})
    clf_review_payload = read_json(clf_review_path, {})
    clf_payload = read_json(clf_path, {})

    if layer_e["status"] == "partial":
        if not allow_path.exists():
            issues.append(
                "Layer E readiness is 'partial' but allow_partial_extraction.json is missing; "
                "create this gate artifact with decision=allow before extraction may proceed"
            )
        elif allow_payload.get("decision") != "allow":
            issues.append(
                f"allow_partial_extraction.json decision is {allow_payload.get('decision')!r}; "
                "extraction requires decision='allow'"
            )

    if not clf_review_path.exists():
        issues.append(
            "missing row classification review artifact: tables/table_row_classification_review_decisions.json"
        )
    else:
        clf_review_decision = clf_review_payload.get("decision")
        if clf_review_decision != "accept":
            issues.append(
                f"row classification review decision is {clf_review_decision!r}; expected 'accept'"
            )

    if not clf_path.exists():
        issues.append("missing row classification artifact: tables/table_row_classification.json")
    elif clf_payload.get("status") != "ok":
        issues.append(
            f"table_row_classification.json status is {clf_payload.get('status')!r}, expected 'ok'"
        )

    return {
        "created_at": now_iso(),
        "status": "ok" if not issues else "blocked",
        "issues": issues,
        "layer_e_gate_status": layer_e["status"],
        "extraction_mode": allow_payload.get("extraction_mode") if allow_payload else None,
        "allowed_known_labels": allow_payload.get("allowed_known_labels", []) if allow_payload else [],
    }


def _extract_field_from_cell(cell: Dict[str, Any], accepted_label: str) -> Dict[str, Any]:
    cell_status = cell.get("cell_status", "empty")
    has_conflict = cell.get("has_conflict", False)
    candidate_values: List[Dict[str, Any]] = []
    for engine, engine_cands in cell.get("candidate_texts_by_engine", {}).items():
        for cand in engine_cands:
            raw_conf = float(cand.get("confidence") or 0.0)
            candidate_values.append({
                "engine": engine,
                "region_id": cand.get("region_id"),
                "text": cand.get("text"),
                "confidence": round(raw_conf / 100.0 if raw_conf > 1.0 else raw_conf, 4),
                "classification": cand.get("classification"),
            })
    if has_conflict or cell_status == "empty":
        extracted_value = None
    else:
        extracted_value = _cell_best_text(cell) or None
    return {
        "cell_id": cell.get("cell_id", ""),
        "column_id": cell.get("column_id", ""),
        "accepted_label": accepted_label,
        "cell_status": cell_status,
        "has_conflict": has_conflict,
        "confidence": cell.get("cell_confidence", 0.0),
        "extracted_value": extracted_value,
        "requires_verification": has_conflict,
        "candidate_values": candidate_values,
    }


def _build_line_item(
    product_row: Dict[str, Any],
    product_cells: List[Dict[str, Any]],
    continuation_pairs: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]],
    accepted_labels: Dict[str, str],
    allowed_labels: Sequence[str],
    extraction_mode: str,
    line_index: int,
    page_number: int,
) -> Dict[str, Any]:
    label_to_col = {lbl: col_id for col_id, lbl in accepted_labels.items() if lbl != "unknown"}
    unknown_col_ids = [col_id for col_id, lbl in accepted_labels.items() if lbl == "unknown"]
    cells_by_col = {c.get("column_id", ""): c for c in product_cells}

    extracted_fields: Dict[str, Any] = {}
    excluded_fields: Dict[str, Any] = {}
    row_has_conflicts = False

    for label in allowed_labels:
        col_id = label_to_col.get(label)
        if col_id is None:
            continue
        cell = cells_by_col.get(col_id)
        if cell is None:
            continue
        field = _extract_field_from_cell(cell, label)
        extracted_fields[label] = field
        if field["has_conflict"]:
            row_has_conflicts = True

    for col_id in unknown_col_ids:
        cell = cells_by_col.get(col_id)
        if cell is None:
            continue
        excluded_fields[col_id] = {
            "accepted_label": "unknown",
            "cell_id": cell.get("cell_id"),
            "cell_status": cell.get("cell_status"),
            "cell_preserved": True,
            "reason": "accepted_label=unknown",
        }

    continuation_data: List[Dict[str, Any]] = []
    for cont_row, cont_cells in continuation_pairs:
        cont_by_col = {c.get("column_id", ""): c for c in cont_cells}
        cont_fields: Dict[str, Any] = {}
        cont_excluded: Dict[str, Any] = {}
        for label in allowed_labels:
            col_id = label_to_col.get(label)
            if col_id is None:
                continue
            cell = cont_by_col.get(col_id)
            if cell is None:
                continue
            field = _extract_field_from_cell(cell, label)
            cont_fields[label] = field
            if field["has_conflict"]:
                row_has_conflicts = True
        for col_id in unknown_col_ids:
            cell = cont_by_col.get(col_id)
            if cell is None:
                continue
            cont_excluded[col_id] = {
                "accepted_label": "unknown",
                "cell_id": cell.get("cell_id"),
                "cell_status": cell.get("cell_status"),
                "cell_preserved": True,
                "reason": "accepted_label=unknown",
            }
        continuation_data.append({
            "row_id": cont_row.get("row_id", ""),
            "extracted_fields": cont_fields,
            "excluded_fields": cont_excluded,
        })

    row_id = product_row.get("row_id", "")
    return {
        "line_item_id": f"page-{page_number:04d}-line-item-{line_index:04d}",
        "row_id": row_id,
        "row_classification": "product_line",
        "extraction_mode": extraction_mode,
        "extraction_complete": False,
        "row_has_conflicts": row_has_conflicts,
        "continuation_rows": [r.get("row_id", "") for r, _ in continuation_pairs],
        "extracted_fields": extracted_fields,
        "excluded_fields": excluded_fields,
        "continuation_data": continuation_data,
    }


def _line_item_csv_row(item: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "line_item_id": item["line_item_id"],
        "row_id": item["row_id"],
        "extraction_complete": item["extraction_complete"],
        "row_has_conflicts": item["row_has_conflicts"],
    }
    for label in ["description", "unit", "quantity", "unit_price"]:
        field = item.get("extracted_fields", {}).get(label)
        if field is None:
            row[label] = "[NOT_EXTRACTED]"
        elif field["cell_status"] == "empty":
            row[label] = "[EMPTY]"
        elif field["has_conflict"]:
            row[label] = "[CONFLICT]"
        else:
            row[label] = field.get("extracted_value") or ""
    row["excluded_col_count"] = len(item.get("excluded_fields", {}))
    row["continuation_row_ids"] = "|".join(item.get("continuation_rows", []))
    return row


def build_line_items_summary_markdown(
    output_path: Path,
    items_payload: Dict[str, Any],
    flags_payload: Dict[str, Any],
) -> None:
    lines = [
        "# Table Line Items Summary",
        "",
        f"Generated: {items_payload.get('created_at', now_iso())}",
        "",
        "- Scope: `Layer E partial extraction only`",
        f"- Page: `{items_payload.get('page')}`",
        f"- Band ID: `{items_payload.get('band_id')}`",
        "",
        "## Extraction Mode",
        "",
        f"- Mode: `{items_payload.get('extraction_mode')}`",
        f"- Extraction complete: `{items_payload.get('extraction_complete')}`",
        f"- Allowed labels: {', '.join(f'`{l}`' for l in flags_payload.get('allowed_known_labels', []))}",
        f"- Excluded columns: {', '.join(f'`{c}`' for c in flags_payload.get('excluded_unknown_columns', []))}",
        "",
        "## Summary",
        "",
        f"- Line items extracted: `{items_payload.get('line_item_count')}`",
        f"- Continuation rows linked: `{items_payload.get('continuation_row_count')}`",
        f"- Rows excluded: `{items_payload.get('excluded_row_count')}`",
        f"- Conflicting fields requiring verification: `{flags_payload.get('conflicting_field_count')}`",
        "",
        "## Line Items",
        "",
    ]
    for item in items_payload.get("line_items", []):
        lines.extend([
            f"### {item['line_item_id']} (row `{item['row_id']}`)",
            "",
            f"- Extraction complete: `{item['extraction_complete']}`",
            f"- Row has conflicts: `{item['row_has_conflicts']}`",
            f"- Continuation rows: `{item.get('continuation_rows', [])}`",
            "",
            "**Extracted fields:**",
            "",
        ])
        for label, field in item.get("extracted_fields", {}).items():
            if field["has_conflict"]:
                val_str = "`[CONFLICT]` — requires_verification=True"
            elif field["cell_status"] == "empty":
                val_str = "`[EMPTY]`"
            else:
                val_str = f"`{field.get('extracted_value', '')}`"
            lines.append(
                f"  - `{label}` ({field['cell_id']}): {val_str} confidence `{field['confidence']}`"
            )
        excl = item.get("excluded_fields", {})
        if excl:
            lines.extend(["", "**Excluded unknown columns:**", ""])
            for col_id, ef in excl.items():
                lines.append(f"  - `{col_id}` ({ef.get('cell_status')}): cell_preserved=True")
        for cont in item.get("continuation_data", []):
            lines.extend(["", f"**Continuation row `{cont['row_id']}`:**", ""])
            for label, field in cont.get("extracted_fields", {}).items():
                if field["has_conflict"]:
                    val_str = "`[CONFLICT]` — requires_verification=True"
                elif field["cell_status"] == "empty":
                    val_str = "`[EMPTY]`"
                else:
                    val_str = f"`{field.get('extracted_value', '')}`"
                lines.append(f"  - `{label}`: {val_str} confidence `{field['confidence']}`")
        lines.append("")
    excluded = items_payload.get("excluded_rows", [])
    if excluded:
        lines.extend(["## Excluded Rows", ""])
        for er in excluded:
            lines.append(f"- `{er['row_id']}`: {er['reason']}")
        lines.append("")
    lines.extend([
        "## Scope Notes",
        "",
        "- Layer E performs partial extraction only. No product matching.",
        "- No SKU lookup, stock update, receiving workflow, or invoice import.",
        "- Conflicting fields have extracted_value=null and requires_verification=true.",
        "- Unknown columns are excluded; their raw cells remain in table_cells.json.",
    ])
    write_markdown(output_path, lines)


def run_layer_e_partial_extraction(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    readiness = validate_layer_e_partial_readiness(run_dir, page_number=page_number, band_id=band_id)
    if readiness["status"] == "blocked":
        return {
            "created_at": now_iso(),
            "status": "blocked",
            "issues": readiness["issues"],
        }

    cells_payload = read_json(tables_dir / "table_cells.json", {})
    sem_review = read_json(tables_dir / "table_column_semantics_review_decisions.json", {})
    clf_payload = read_json(tables_dir / "table_row_classification.json", {})
    clf_review = read_json(tables_dir / "table_row_classification_review_decisions.json", {})
    allow_payload = read_json(tables_dir / "allow_partial_extraction.json", {})

    accepted_labels: Dict[str, str] = sem_review.get("accepted_labels", {})
    extraction_mode: str = allow_payload.get("extraction_mode", "partial")
    allowed_labels: List[str] = allow_payload.get("allowed_known_labels", [])

    confirmed_classes: Dict[str, str] = {
        d.get("row_id", ""): d.get("confirmed_class", "")
        for d in clf_review.get("decisions", [])
    }

    cells_by_row: Dict[str, List[Dict[str, Any]]] = {}
    for cell in cells_payload.get("cells", []):
        cells_by_row.setdefault(cell.get("row_id", ""), []).append(cell)

    line_items: List[Dict[str, Any]] = []
    excluded_rows: List[Dict[str, str]] = []
    pending_product_row: Optional[Dict[str, Any]] = None
    pending_continuations: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    line_index = 0

    def _flush() -> None:
        nonlocal pending_product_row, pending_continuations, line_index
        if pending_product_row is not None:
            line_index += 1
            line_items.append(_build_line_item(
                pending_product_row,
                cells_by_row.get(pending_product_row.get("row_id", ""), []),
                pending_continuations,
                accepted_labels, allowed_labels, extraction_mode,
                line_index, page_number,
            ))
        pending_product_row = None
        pending_continuations = []

    for clf_row in clf_payload.get("rows", []):
        row_id = clf_row.get("row_id", "")
        cls = confirmed_classes.get(row_id, clf_row.get("classification", ""))
        if cls == "product_line":
            _flush()
            pending_product_row = clf_row
        elif cls == "continuation_row":
            if pending_product_row is not None:
                pending_continuations.append((clf_row, cells_by_row.get(row_id, [])))
            else:
                excluded_rows.append({"row_id": row_id, "reason": "continuation_row without preceding product_line"})
        elif cls == "header":
            pass
        else:
            _flush()
            excluded_rows.append({"row_id": row_id, "reason": f"row class={cls!r} excluded from extraction"})

    _flush()

    conflicting_field_count = sum(
        1 for li in line_items
        for field in li.get("extracted_fields", {}).values()
        if field.get("has_conflict")
    ) + sum(
        1 for li in line_items
        for cont in li.get("continuation_data", [])
        for field in cont.get("extracted_fields", {}).values()
        if field.get("has_conflict")
    )
    continuation_row_count = sum(len(li.get("continuation_rows", [])) for li in line_items)

    items_payload: Dict[str, Any] = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "implemented_layers": ["partial_extraction"],
            "excluded_layers": [
                "invoice_extraction", "product_matching",
                "receiving_workflow", "sku_lookup", "stock_update",
            ],
        },
        "page": page_number,
        "band_id": band_id,
        "extraction_mode": extraction_mode,
        "extraction_complete": False,
        "line_item_count": len(line_items),
        "continuation_row_count": continuation_row_count,
        "excluded_row_count": len(excluded_rows),
        "line_items": line_items,
        "excluded_rows": excluded_rows,
    }

    flags_payload: Dict[str, Any] = {
        "created_at": now_iso(),
        "extraction_mode": extraction_mode,
        "extraction_complete": False,
        "allow_partial_extraction_gate": "tables/allow_partial_extraction.json",
        "allowed_known_labels": allowed_labels,
        "excluded_unknown_columns": [c for c, l in accepted_labels.items() if l == "unknown"],
        "line_item_count": len(line_items),
        "continuation_row_count": continuation_row_count,
        "excluded_row_count": len(excluded_rows),
        "conflicting_field_count": conflicting_field_count,
        "notes": [
            "No product matching, SKU lookup, stock update, or receiving workflow performed.",
            "Unknown columns are excluded; their cells are preserved in table_cells.json.",
            "Conflicting fields carry extracted_value=null and requires_verification=true.",
        ],
    }

    write_json(tables_dir / "table_line_items.json", items_payload)
    write_json(tables_dir / "layer_e_extraction_flags.json", flags_payload)
    write_csv(tables_dir / "table_line_items.csv", [_line_item_csv_row(li) for li in line_items])
    build_line_items_summary_markdown(
        tables_dir / "table_line_items_summary.md", items_payload, flags_payload
    )
    return items_payload


# ---------------------------------------------------------------------------
# Layer E line-item review gate
# ---------------------------------------------------------------------------

_DEFAULT_LINE_ITEMS_REVIEW_NOTES: List[str] = [
    "Partial extraction accepted for description, unit, quantity, and unit_price only.",
    "Continuation row is linked, not extracted as separate product.",
    "Conflict is preserved for human/product matching awareness.",
    "No product matching, SKU lookup, stock update, receiving workflow, or invoice import is approved.",
]


def build_line_items_review_markdown(output_path: Path, payload: Dict[str, Any]) -> None:
    decision = payload.get("decision", "")
    accepted = payload.get("accepted_line_items", [])
    flagged = payload.get("flagged_items", {})
    lines = [
        "# Table Line Items Review Decisions",
        "",
        f"Generated: {payload.get('created_at', now_iso())}",
        "",
        "## Line Item Extraction Review",
        "",
        f"- Reviewed artifact: `{payload.get('reviewed_artifact')}`",
        f"- Decision: `{decision}`",
        f"- Reviewer timestamp: `{payload.get('reviewer_timestamp')}`",
        "",
        "## Accepted Line Items",
        "",
    ]
    for item_id in accepted:
        flag = flagged.get(item_id)
        flag_str = f"  *(flagged: {flag['reason']})*" if flag else ""
        lines.append(f"- `{item_id}`{flag_str}")
    excl_rows = payload.get("excluded_rows_acknowledged", [])
    if excl_rows:
        lines.extend(["", "## Excluded Rows Acknowledged", ""])
        for er in excl_rows:
            lines.append(f"- `{er.get('row_id')}`: {er.get('reason')}")
    excl_cols = payload.get("excluded_unknown_columns_acknowledged", [])
    if excl_cols:
        lines.extend(["", "## Excluded Unknown Columns Acknowledged", ""])
        for col_id in excl_cols:
            lines.append(f"- `{col_id}`")
    notes = payload.get("notes", [])
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in notes)
    lines.extend([
        "",
        "## Scope",
        "",
        "- Line-item review only. No product matching approved by this review.",
        "- No SKU lookup, stock update, receiving workflow, or invoice import approved.",
        "- Flagged items must be handled with conflict awareness in any downstream process.",
    ])
    write_markdown(output_path, lines)


def write_line_items_review_decision(
    run_dir: Path,
    decision: str = "accept_with_flags",
    notes: Optional[List[str]] = None,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    valid = {"accept", "accept_with_flags", "reject", "needs_reextraction"}
    if decision not in valid:
        raise ValueError(f"Line-items review decision must be one of {sorted(valid)}, got {decision!r}")
    if notes is None:
        notes = _DEFAULT_LINE_ITEMS_REVIEW_NOTES

    tables_dir = run_dir / "tables"
    items_payload = read_json(tables_dir / "table_line_items.json", {})
    flags_payload = read_json(tables_dir / "layer_e_extraction_flags.json", {})

    line_items = items_payload.get("line_items", [])
    accepted_line_items: List[str] = [li["line_item_id"] for li in line_items]

    # Auto-derive flagged items from rows_has_conflicts
    flagged_items: Dict[str, Any] = {}
    for li in line_items:
        if not li.get("row_has_conflicts"):
            continue
        conflicting_parts: List[str] = []
        for label, field in li.get("extracted_fields", {}).items():
            if field.get("has_conflict"):
                conflicting_parts.append(f"{label} (row {li['row_id']})")
        for cont in li.get("continuation_data", []):
            for label, field in cont.get("extracted_fields", {}).items():
                if field.get("has_conflict"):
                    conflicting_parts.append(f"{label} (continuation {cont['row_id']})")
        if conflicting_parts:
            flagged_items[li["line_item_id"]] = {
                "reason": (
                    f"conflicting field(s): {', '.join(conflicting_parts)}; "
                    "extracted_value(s) remain null"
                )
            }

    excluded_rows_acknowledged = [
        {"row_id": er["row_id"], "reason": er["reason"]}
        for er in items_payload.get("excluded_rows", [])
    ]
    excluded_unknown_columns_acknowledged = flags_payload.get("excluded_unknown_columns", [])

    payload: Dict[str, Any] = {
        "created_at": now_iso(),
        "status": "ok",
        "scope": {
            "environment_expectation": "staging",
            "pages": [page_number],
            "band_ids": [band_id],
            "reviewed_layer": "line_item_extraction",
            "excluded_layers": [
                "product_matching",
                "sku_lookup",
                "stock_update",
                "receiving_workflow",
                "invoice_import",
            ],
        },
        "reviewed_artifact": "tables/table_line_items_summary.md",
        "decision": decision,
        "accepted_line_items": accepted_line_items,
        "flagged_items": flagged_items,
        "excluded_rows_acknowledged": excluded_rows_acknowledged,
        "excluded_unknown_columns_acknowledged": excluded_unknown_columns_acknowledged,
        "notes": notes,
        "reviewer_timestamp": now_iso(),
    }

    json_path = tables_dir / "table_line_items_review_decisions.json"
    md_path = tables_dir / "table_line_items_review_decisions.md"
    write_json(json_path, payload)
    build_line_items_review_markdown(md_path, payload)
    return payload


# ---------------------------------------------------------------------------
# Product Matching readiness gate (product matching not yet implemented)
# ---------------------------------------------------------------------------

def validate_product_matching_readiness(
    run_dir: Path,
    page_number: int = 3,
    band_id: str = "page-0003-table-band-0001",
) -> Dict[str, Any]:
    tables_dir = run_dir / "tables"
    items_path = tables_dir / "table_line_items.json"
    review_path = tables_dir / "table_line_items_review_decisions.json"

    items_payload = read_json(items_path, {})
    review_payload = read_json(review_path, {})

    issues: List[str] = []
    warnings: List[str] = []

    if not items_path.exists():
        issues.append("missing Layer E artifact: tables/table_line_items.json")
    elif items_payload.get("status") != "ok":
        issues.append(
            f"table_line_items.json status is {items_payload.get('status')!r}, expected 'ok'"
        )

    if not review_path.exists():
        issues.append(
            "missing line-item review artifact: tables/table_line_items_review_decisions.json"
        )
    else:
        decision = review_payload.get("decision")
        if decision not in {"accept", "accept_with_flags"}:
            issues.append(
                f"line-item review decision is {decision!r}; "
                "product matching requires 'accept' or 'accept_with_flags'"
            )
        reviewed_artifact = review_payload.get("reviewed_artifact")
        if reviewed_artifact != "tables/table_line_items_summary.md":
            issues.append(
                f"line-item review reviewed_artifact is {reviewed_artifact!r}, "
                "expected 'tables/table_line_items_summary.md'"
            )
        accepted = review_payload.get("accepted_line_items", [])
        if not accepted:
            issues.append(
                "line-item review accepted_line_items is empty; "
                "no line items are accepted for product matching"
            )
        scope = review_payload.get("scope", {})
        required_excluded = {"product_matching", "sku_lookup", "stock_update", "receiving_workflow"}
        if not required_excluded.issubset(set(scope.get("excluded_layers", []))):
            issues.append(
                "line-item review scope does not explicitly exclude product-matching/business layers"
            )

    line_item_count = items_payload.get("line_item_count", 0)
    if items_path.exists() and items_payload.get("status") == "ok" and line_item_count == 0:
        issues.append(
            "table_line_items.json contains no line items; "
            "product matching requires at least one extracted line item"
        )

    flagged = review_payload.get("flagged_items", {}) if review_payload else {}
    for item_id, flag_info in flagged.items():
        warnings.append(
            f"{item_id} is flagged: {flag_info.get('reason', '')}; "
            "product matching must handle this with conflict awareness"
        )

    return {
        "created_at": now_iso(),
        "status": "ok" if not issues else "blocked",
        "issues": issues,
        "warnings": warnings,
        "line_item_review_decision": review_payload.get("decision") if review_payload else None,
        "accepted_line_items": review_payload.get("accepted_line_items", []) if review_payload else [],
        "flagged_item_count": len(flagged),
        "line_item_count": line_item_count,
    }


def build_product_matching_readiness_markdown(output_path: Path, readiness: Dict[str, Any]) -> None:
    lines = [
        "# Product Matching Readiness",
        "",
        f"Generated: {now_iso()}",
        "",
        f"- Status: `{readiness.get('status')}`",
        f"- Line-item review decision: `{readiness.get('line_item_review_decision')}`",
        f"- Line items: `{readiness.get('line_item_count')}`",
        f"- Flagged items: `{readiness.get('flagged_item_count')}`",
        "",
        "## Gate Checks",
        "",
    ]
    issues = readiness.get("issues", [])
    if issues:
        lines.extend(f"- FAIL: {issue}" for issue in issues)
    else:
        lines.append("- All upstream gate checks passed.")
    warnings = readiness.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- WARN: {w}" for w in warnings)
    accepted = readiness.get("accepted_line_items", [])
    if accepted:
        lines.extend(["", "## Accepted Line Items", ""])
        for item_id in accepted:
            lines.append(f"- `{item_id}`")
    lines.extend([
        "",
        "## Gate Decision",
        "",
        "- `ok` — all gates passed. Product matching design may proceed.",
        "- `blocked` — hard gate failure. Product matching must not run.",
        "",
        "- Product matching is NOT yet implemented. This gate confirms readiness only.",
        "- Flagged items must be handled with conflict awareness in product matching.",
        "- No SKU lookup, stock update, receiving workflow, or invoice import is permitted "
        "until product matching is designed and reviewed.",
    ])
    write_markdown(output_path, lines)


# ---------------------------------------------------------------------------
# Line-items extraction preview (display-only)
# ---------------------------------------------------------------------------

def build_line_items_preview(run_dir: Path, page_number: int = 3) -> str:
    """Render a human-readable preview of extracted line items. Returns the preview text."""
    tables_dir = run_dir / "tables"
    payload = read_json(tables_dir / "table_line_items.json", {})

    header = [
        "# Line Items Extraction Preview",
        "",
        f"Generated: {now_iso()}",
        f"Source: tables/table_line_items.json",
        f"Extraction mode: {payload.get('extraction_mode', 'unknown')}",
        f"Extraction complete: {payload.get('extraction_complete', False)}",
        f"Line items: {payload.get('line_item_count', 0)}",
        "",
        "> Display-only. No extraction logic, product matching, or upstream artifacts modified.",
    ]

    body: List[str] = []
    for idx, item in enumerate(payload.get("line_items", []), 1):
        item_id = item.get("line_item_id", "")
        row_id = item.get("row_id", "")
        extraction_complete = item.get("extraction_complete", False)
        row_has_conflicts = item.get("row_has_conflicts", False)
        continuation_rows = item.get("continuation_rows", [])

        body.extend([
            "",
            "---",
            "",
            f"## Line Item {idx} — {item_id}",
            "",
            f"Source row: `{row_id}`",
            f"Extraction complete: `{extraction_complete}`",
            f"Row has conflicts: `{row_has_conflicts}`",
        ])
        if continuation_rows:
            body.append(f"Continuation rows: {', '.join(f'`{r}`' for r in continuation_rows)}")

        # Extracted fields table
        extracted = item.get("extracted_fields", {})
        if extracted:
            body.extend([
                "",
                "**Extracted fields:**",
                "",
                "| Field | Value | Confidence | Status |",
                "|---|---|---|---|",
            ])
            for label in ["description", "unit", "quantity", "unit_price"]:
                field = extracted.get(label)
                if field is None:
                    continue
                if field.get("has_conflict"):
                    val = "[CONFLICT — extracted_value=null]"
                    status = "conflicting"
                elif field.get("cell_status") == "empty":
                    val = "[EMPTY]"
                    status = "empty"
                else:
                    raw = field.get("extracted_value") or ""
                    val = raw if raw else "[no text]"
                    status = field.get("cell_status", "")
                conf = field.get("confidence", 0.0)
                body.append(f"| `{label}` | {val} | {conf} | {status} |")

        # Excluded unknown columns
        excl = item.get("excluded_fields", {})
        if excl:
            body.extend(["", "**Excluded unknown columns:**", ""])
            for col_id, ef in excl.items():
                body.append(
                    f"- `{col_id}` ({ef.get('cell_status', '?')}) — "
                    f"cell_preserved={ef.get('cell_preserved', True)}"
                )

        # Continuation data
        for cont in item.get("continuation_data", []):
            cont_row_id = cont.get("row_id", "")
            cont_fields = cont.get("extracted_fields", {})
            body.extend(["", f"**Continuation row `{cont_row_id}`:**", ""])
            if cont_fields:
                body.extend([
                    "| Field | Value | Confidence | Status |",
                    "|---|---|---|---|",
                ])
                for label in ["description", "unit", "quantity", "unit_price"]:
                    field = cont_fields.get(label)
                    if field is None:
                        continue
                    if field.get("has_conflict"):
                        val = "[CONFLICT — extracted_value=null]"
                        status = "conflicting"
                    elif field.get("cell_status") == "empty":
                        val = "[EMPTY]"
                        status = "empty"
                    else:
                        raw = field.get("extracted_value") or ""
                        val = raw if raw else "[no text]"
                        status = field.get("cell_status", "")
                    conf = field.get("confidence", 0.0)
                    body.append(f"| `{label}` | {val} | {conf} | {status} |")
            cont_excl = cont.get("excluded_fields", {})
            if cont_excl:
                body.extend(["", "Excluded unknown columns (continuation):", ""])
                for col_id, ef in cont_excl.items():
                    body.append(
                        f"- `{col_id}` ({ef.get('cell_status', '?')}) — "
                        f"cell_preserved={ef.get('cell_preserved', True)}"
                    )

    # Excluded rows
    excluded_rows = payload.get("excluded_rows", [])
    if excluded_rows:
        body.extend(["", "---", "", "## Excluded Rows", ""])
        for er in excluded_rows:
            body.append(f"- `{er.get('row_id')}`: {er.get('reason')}")

    body.extend([
        "",
        "---",
        "",
        "## Notes",
        "",
        "- Values shown as-extracted. No normalisation or product matching applied.",
        "- `[CONFLICT]` fields have `extracted_value=null`; all candidate values are in table_line_items.json.",
        "- Excluded columns are preserved in table_cells.json.",
    ])

    all_lines = header + body
    return "\n".join(all_lines) + "\n"


def run_line_items_preview(run_dir: Path, page_number: int = 3) -> str:
    """Write table_line_items_preview.md and return its content."""
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    content = build_line_items_preview(run_dir, page_number=page_number)
    output_path = tables_dir / "table_line_items_preview.md"
    output_path.write_text(content, encoding="utf-8")
    return content


# ---------------------------------------------------------------------------
# Extraction diagnostic report with cell crops
# ---------------------------------------------------------------------------

_CROP_PADDING = 8  # pixels of context around each cell bbox


def _save_cell_crop(
    page_img: Any,
    cell_bbox: Sequence[int],
    output_path: Path,
    img_size: Tuple[int, int],
) -> bool:
    """Crop a cell from the page image with padding and save as PNG. Returns True on success."""
    try:
        iw, ih = img_size
        x1 = max(0, int(cell_bbox[0]) - _CROP_PADDING)
        y1 = max(0, int(cell_bbox[1]) - _CROP_PADDING)
        x2 = min(iw, int(cell_bbox[2]) + _CROP_PADDING)
        y2 = min(ih, int(cell_bbox[3]) + _CROP_PADDING)
        if x2 <= x1 or y2 <= y1:
            return False
        cropped = page_img.crop((x1, y1, x2, y2))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(str(output_path), format="PNG")
        return True
    except Exception:
        return False


def _diagnostic_field_section(
    label: str,
    field: Dict[str, Any],
    cell: Dict[str, Any],
    crop_rel_path: str,
    crop_saved: bool,
) -> List[str]:
    lines: List[str] = []
    cell_id = field.get("cell_id", "")
    bbox = cell.get("cell_bbox", [])
    has_conflict = field.get("has_conflict", False)
    cell_status = field.get("cell_status", "")
    confidence = field.get("confidence", 0.0)
    extracted = field.get("extracted_value")

    lines.extend([
        f"### `{label}` — {cell_id}",
        "",
        f"- **Extracted value:** `{extracted}`" if extracted is not None else "- **Extracted value:** `null`",
        f"- **Cell status:** {cell_status}",
        f"- **Has conflict:** {has_conflict}",
        f"- **Cell confidence:** {confidence}",
        f"- **Cell bbox:** {bbox}",
        f"- **Crop:** `{crop_rel_path}`" + ("" if crop_saved else " *(crop failed)*"),
    ])
    if has_conflict:
        lines.append("- **Requires verification:** True — do not use extracted_value without human review")

    cands = field.get("candidate_values", [])
    if cands:
        lines.extend(["", "**OCR candidates by engine:**", ""])
        # Group by engine preserving order
        engines_seen: List[str] = []
        by_engine: Dict[str, List[Dict[str, Any]]] = {}
        for cand in cands:
            eng = cand.get("engine", "?")
            if eng not in by_engine:
                engines_seen.append(eng)
                by_engine[eng] = []
            by_engine[eng].append(cand)
        lines.extend([
            "| Engine | Text | Confidence | Classification |",
            "|---|---|---|---|",
        ])
        for eng in engines_seen:
            for cand in by_engine[eng]:
                text = (cand.get("text") or "").replace("|", "\\|")
                conf = round(cand.get("confidence", 0.0), 4)
                clf = cand.get("classification", "")
                lines.append(f"| {eng} | {text} | {conf} | {clf} |")
    lines.append("")
    return lines


def run_extraction_diagnostic(
    run_dir: Path,
    page_number: int = 3,
) -> str:
    """Produce extraction_diagnostic.md and debug cell crops. Returns the markdown content."""
    tables_dir = run_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    crops_dir = tables_dir / "debug_crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    items_payload = read_json(tables_dir / "table_line_items.json", {})
    cells_payload = read_json(tables_dir / "table_cells.json", {})
    cells_by_id: Dict[str, Dict[str, Any]] = {
        c["cell_id"]: c for c in cells_payload.get("cells", [])
    }

    # Load page image
    page_image_path = run_dir / "pages" / f"page-{page_number:04d}.png"
    pil_image_mod, pil_err = import_optional("PIL.Image")
    page_img = None
    img_size: Tuple[int, int] = (0, 0)
    if not pil_err and page_image_path.exists():
        page_img = pil_image_mod.open(str(page_image_path)).convert("RGB")
        img_size = page_img.size

    def _crop(cell_id: str) -> Tuple[str, bool]:
        """Returns (relative path for markdown, was_saved)."""
        cell = cells_by_id.get(cell_id, {})
        bbox = cell.get("cell_bbox", [])
        rel = f"debug_crops/{cell_id}.png"
        if not bbox or page_img is None:
            return rel, False
        saved = _save_cell_crop(page_img, bbox, crops_dir / f"{cell_id}.png", img_size)
        return rel, saved

    md: List[str] = [
        "# Extraction Diagnostic Report",
        "",
        f"Generated: {now_iso()}",
        f"Page image: `pages/page-{page_number:04d}.png`"
        + (f"  ({img_size[0]}x{img_size[1]} px)" if img_size[0] else "  *(image not found)*"),
        f"Source: `tables/table_line_items.json`",
        "",
        "> Diagnostic only. No OCR, extraction logic, or upstream artifacts modified.",
        "",
    ]

    for li_idx, li in enumerate(items_payload.get("line_items", []), 1):
        item_id = li.get("line_item_id", "")
        row_id = li.get("row_id", "")
        md.extend([
            "---",
            "",
            f"## Line Item {li_idx} — {item_id}",
            "",
            f"Source row: `{row_id}`  |  "
            f"Extraction complete: `{li.get('extraction_complete')}`  |  "
            f"Row has conflicts: `{li.get('row_has_conflicts')}`",
            f"Continuation rows: {li.get('continuation_rows', [])}",
            "",
        ])

        # Extracted fields (product line row)
        extracted = li.get("extracted_fields", {})
        if extracted:
            md.append("### Extracted fields (product line row)")
            md.append("")
            for label in ["description", "unit", "quantity", "unit_price"]:
                field = extracted.get(label)
                if field is None:
                    continue
                cid = field.get("cell_id", "")
                cell = cells_by_id.get(cid, {})
                rel, saved = _crop(cid)
                md.extend(_diagnostic_field_section(label, field, cell, rel, saved))

        # Excluded unknown columns
        excl = li.get("excluded_fields", {})
        if excl:
            md.extend([
                "### Excluded unknown columns",
                "",
                "These columns have no accepted semantic label. "
                "Cell crops and raw OCR are shown for visual inspection only.",
                "",
            ])
            for col_id, ef in excl.items():
                # Find the cell for this column in the product row
                cid = ef.get("cell_id", "")
                cell = cells_by_id.get(cid, {})
                bbox = cell.get("cell_bbox", [])
                rel, saved = _crop(cid)
                md.extend([
                    f"#### `{col_id}` — {cid}",
                    "",
                    f"- **Accepted label:** unknown",
                    f"- **Cell status:** {ef.get('cell_status', '')}",
                    f"- **Cell bbox:** {bbox}",
                    f"- **Crop:** `{rel}`" + ("" if saved else " *(crop failed)*"),
                    f"- **Cell preserved in table_cells.json:** {ef.get('cell_preserved', True)}",
                ])
                raw_cands = cell.get("candidate_texts_by_engine", {})
                if raw_cands:
                    md.extend(["", "**Raw OCR candidates:**", ""])
                    md.extend([
                        "| Engine | Text | Confidence | Classification |",
                        "|---|---|---|---|",
                    ])
                    for eng, cands in raw_cands.items():
                        for cand in cands:
                            text = (cand.get("text") or "").replace("|", "\\|")
                            raw_conf = float(cand.get("confidence") or 0.0)
                            norm_conf = round(raw_conf / 100.0 if raw_conf > 1.0 else raw_conf, 4)
                            clf = cand.get("classification", "")
                            md.append(f"| {eng} | {text} | {norm_conf} | {clf} |")
                md.append("")

        # Continuation rows
        for cont in li.get("continuation_data", []):
            cont_row_id = cont.get("row_id", "")
            md.extend([
                f"### Continuation row `{cont_row_id}`",
                "",
            ])
            for label in ["description", "unit", "quantity", "unit_price"]:
                field = cont.get("extracted_fields", {}).get(label)
                if field is None:
                    continue
                cid = field.get("cell_id", "")
                cell = cells_by_id.get(cid, {})
                rel, saved = _crop(cid)
                md.extend(_diagnostic_field_section(label, field, cell, rel, saved))
            cont_excl = cont.get("excluded_fields", {})
            if cont_excl:
                md.append("**Excluded unknown columns (continuation):**")
                md.append("")
                for col_id, ef in cont_excl.items():
                    cid = ef.get("cell_id", "")
                    cell = cells_by_id.get(cid, {})
                    bbox = cell.get("cell_bbox", [])
                    rel, saved = _crop(cid)
                    md.extend([
                        f"- `{col_id}` — {cid}  status={ef.get('cell_status','')}  "
                        f"bbox={bbox}  crop=`{rel}`" + ("" if saved else " *(failed)*"),
                    ])
                md.append("")

    md.extend([
        "---",
        "",
        "## Crop Index",
        "",
        "All crops saved to `tables/debug_crops/` with 8px padding.",
        f"Page image size: {img_size[0]}x{img_size[1]} px" if img_size[0] else "Page image not found.",
        "",
        "## Notes",
        "",
        "- Crops reflect raw cell geometry from Layer C column reconstruction.",
        "- Confidence values > 1.0 in source JSON (Tesseract scale) are normalised to 0-1 here.",
        "- Conflicting cells have no single extracted value; all candidate readings are shown.",
        "- This report does not change OCR output, extraction logic, or any pipeline artifact.",
    ])

    content = "\n".join(md) + "\n"
    output_path = tables_dir / "extraction_diagnostic.md"
    output_path.write_text(content, encoding="utf-8")
    return content


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run raw-output-first OCR feasibility extraction on invoice PDFs.")
    parser.add_argument("input", nargs="?", type=Path, help="PDF file or directory containing PDFs.")
    parser.add_argument("--env", choices=["production", "staging"], help="Environment profile for inbound/output defaults.")
    parser.add_argument("--out", type=Path, help="Output root directory.")
    parser.add_argument(
        "--fuse-run-dir",
        type=Path,
        help="Run only the region-level fusion stage against an existing run directory that already contains OCR outputs.",
    )
    parser.add_argument(
        "--zone-run-dir",
        type=Path,
        help="Run only the region-zoning stage against an existing run directory that already contains fusion outputs.",
    )
    parser.add_argument(
        "--table-band-run-dir",
        type=Path,
        help="Run only the Layer A table-band detection proof of concept against an existing run directory.",
    )
    parser.add_argument(
        "--table-row-run-dir",
        type=Path,
        help="Run only the Layer B row reconstruction proof of concept against an existing run directory.",
    )
    parser.add_argument(
        "--table-column-run-dir",
        type=Path,
        help="Run the Layer C column reconstruction proof of concept against an existing staging run directory after validating Layer B.",
    )
    parser.add_argument(
        "--table-column-review-run-dir",
        type=Path,
        help="Record a staging Layer C column-geometry review decision for an existing run directory.",
    )
    parser.add_argument(
        "--table-column-review-decision",
        choices=["accept", "reject", "needs_adjustment"],
        default="accept",
        help="Column-geometry review decision to record with --table-column-review-run-dir.",
    )
    parser.add_argument(
        "--table-column-review-notes",
        default="Accepted staging Layer C column geometry overlay for page 3. Geometry only; no semantic column meanings assigned.",
        help="Notes to store with the column-geometry review decision.",
    )
    parser.add_argument(
        "--layer-d-readiness-run-dir",
        type=Path,
        help="Check whether staging artifacts are ready for Layer D semantic work without running Layer D.",
    )
    parser.add_argument(
        "--table-semantics-run-dir",
        type=Path,
        help="Run Layer D column semantic labeling against an existing staging run directory.",
    )
    parser.add_argument(
        "--table-semantics-review-run-dir",
        type=Path,
        help="Record a staging Layer D semantic label review decision for an existing run directory.",
    )
    parser.add_argument(
        "--table-semantics-review-decision",
        choices=["accept", "accept_with_adjustments", "reject", "needs_more_evidence"],
        default="accept_with_adjustments",
        help="Semantic label review decision to record with --table-semantics-review-run-dir.",
    )
    parser.add_argument(
        "--table-semantics-review-notes",
        nargs="*",
        default=None,
        metavar="NOTE",
        help="Notes to store with the semantic review decision. Repeatable. Defaults to staging notes when omitted.",
    )
    parser.add_argument(
        "--layer-e-readiness-run-dir",
        type=Path,
        help="Check whether staging artifacts are ready for Layer E (Layer E is not yet implemented).",
    )
    parser.add_argument(
        "--row-classification-run-dir",
        type=Path,
        help="Run Layer E-0 row classification against an existing staging run directory.",
    )
    parser.add_argument(
        "--row-classification-review-run-dir",
        type=Path,
        help="Record a staging Layer E-0 row classification review decision (confirm-all default).",
    )
    parser.add_argument(
        "--allow-partial-extraction-run-dir",
        type=Path,
        help="Write the allow_partial_extraction gate artifact for an existing staging run directory.",
    )
    parser.add_argument(
        "--allow-partial-extraction-decision",
        choices=["allow", "deny"],
        default="allow",
        help="Decision to record in allow_partial_extraction.json.",
    )
    parser.add_argument(
        "--layer-e-extract-run-dir",
        type=Path,
        help="Run Layer E partial extraction against an existing staging run directory.",
    )
    parser.add_argument(
        "--line-items-review-run-dir",
        type=Path,
        help="Record a staging Layer E line-item review decision for an existing run directory.",
    )
    parser.add_argument(
        "--product-matching-readiness-run-dir",
        type=Path,
        help="Check whether staging artifacts are ready for product matching (not yet implemented).",
    )
    parser.add_argument(
        "--line-items-preview-run-dir",
        type=Path,
        help="Write a human-readable extraction preview (display-only, no logic changes).",
    )
    parser.add_argument(
        "--extraction-diagnostic-run-dir",
        type=Path,
        help="Write extraction_diagnostic.md and debug cell crops (diagnostic only, nothing modified).",
    )
    parser.add_argument("--dpi", type=int, default=240, help="Rasterization DPI.")
    parser.add_argument(
        "--cpu-fast",
        action="store_true",
        help="Use CPU-friendly settings: fewer Tesseract PSM/variant attempts while preserving raw outputs.",
    )
    parser.add_argument("--openai", action="store_true", help="Enable optional OpenAI second-reader stage after OSS OCR.")
    parser.add_argument("--openai-model", default="gpt-4.1", help="OpenAI vision-capable model for second-reader OCR.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    if sys.version_info < MIN_PYTHON:
        minimum = ".".join(str(part) for part in MIN_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        print(
            f"Python {minimum}+ is required. Current interpreter is Python {current}. "
            "Install Python 3.10 or 3.11, recreate .venv, then reinstall requirements.",
            file=sys.stderr,
        )
        return 2
    load_dotenv()
    args = parse_args(argv)
    environment = resolve_environment_name(args.env)
    env_config = environment_config(environment)
    if args.fuse_run_dir:
        validate_environment_path(environment, args.fuse_run_dir, purpose="Fusion run directory")
        summary = run_fusion_only_on_existing_run(args.fuse_run_dir)
        print(f"Fusion updated: {args.fuse_run_dir}")
        print(json.dumps(summary.get("region_counts", {}), ensure_ascii=False, indent=2))
        return 0
    if args.zone_run_dir:
        validate_environment_path(environment, args.zone_run_dir, purpose="Zoning run directory")
        summary = run_zoning_only_on_existing_run(args.zone_run_dir)
        print(f"Zoning updated: {args.zone_run_dir}")
        print(json.dumps(summary.get("zone_counts", {}), ensure_ascii=False, indent=2))
        return 0
    if args.table_band_run_dir:
        validate_environment_path(environment, args.table_band_run_dir, purpose="Table-band run directory")
        summary = run_table_band_detection_poc(args.table_band_run_dir, page_number=3)
        print(f"Table-band detection updated: {args.table_band_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.table_row_run_dir:
        validate_environment_path(environment, args.table_row_run_dir, purpose="Table-row run directory")
        summary = run_table_row_reconstruction_poc(args.table_row_run_dir, page_number=3, band_id="page-0003-table-band-0001")
        print(f"Table-row reconstruction updated: {args.table_row_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.table_column_run_dir:
        validate_environment_path(environment, args.table_column_run_dir, purpose="Table-column run directory")
        summary = run_table_column_reconstruction_poc(args.table_column_run_dir, page_number=3, band_id="page-0003-table-band-0001")
        print(f"Table-column reconstruction checked: {args.table_column_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary.get("status") == "ok" else 1
    if args.table_column_review_run_dir:
        validate_environment_path(environment, args.table_column_review_run_dir, purpose="Table-column review run directory")
        summary = write_table_column_review_decision(
            args.table_column_review_run_dir,
            decision=args.table_column_review_decision,
            notes=args.table_column_review_notes,
            page_number=3,
            band_id="page-0003-table-band-0001",
        )
        print(f"Table-column review recorded: {args.table_column_review_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.layer_d_readiness_run_dir:
        validate_environment_path(environment, args.layer_d_readiness_run_dir, purpose="Layer D readiness run directory")
        summary = validate_layer_d_readiness(args.layer_d_readiness_run_dir, page_number=3, band_id="page-0003-table-band-0001")
        print(f"Layer D readiness checked: {args.layer_d_readiness_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary.get("status") == "ok" else 1
    if args.table_semantics_run_dir:
        validate_environment_path(environment, args.table_semantics_run_dir, purpose="Table-semantics run directory")
        summary = run_table_column_semantics_poc(
            args.table_semantics_run_dir, page_number=3, band_id="page-0003-table-band-0001"
        )
        print(f"Table-column semantics: {args.table_semantics_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary.get("status") == "ok" else 1
    if args.table_semantics_review_run_dir:
        validate_environment_path(
            environment, args.table_semantics_review_run_dir, purpose="Table-semantics review run directory"
        )
        summary = write_table_column_semantics_review_decision(
            args.table_semantics_review_run_dir,
            decision=args.table_semantics_review_decision,
            notes=args.table_semantics_review_notes,
            page_number=3,
            band_id="page-0003-table-band-0001",
        )
        print(f"Table-column semantics review recorded: {args.table_semantics_review_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.layer_e_readiness_run_dir:
        validate_environment_path(
            environment, args.layer_e_readiness_run_dir, purpose="Layer E readiness run directory"
        )
        readiness = validate_layer_e_readiness(
            args.layer_e_readiness_run_dir, page_number=3, band_id="page-0003-table-band-0001"
        )
        tables_dir = args.layer_e_readiness_run_dir / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)
        build_layer_e_readiness_markdown(tables_dir / "layer_e_readiness.md", readiness)
        print(f"Layer E readiness checked: {args.layer_e_readiness_run_dir}")
        print(json.dumps(readiness, ensure_ascii=False, indent=2))
        return 0 if readiness.get("status") == "ok" else 1
    if args.row_classification_run_dir:
        validate_environment_path(
            environment, args.row_classification_run_dir, purpose="Row-classification run directory"
        )
        summary = run_row_classification_poc(
            args.row_classification_run_dir, page_number=3, band_id="page-0003-table-band-0001"
        )
        print(f"Row classification: {args.row_classification_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary.get("status") == "ok" else 1
    if args.row_classification_review_run_dir:
        validate_environment_path(
            environment,
            args.row_classification_review_run_dir,
            purpose="Row-classification review run directory",
        )
        summary = write_row_classification_review_decision(
            args.row_classification_review_run_dir,
            page_number=3,
            band_id="page-0003-table-band-0001",
        )
        print(f"Row classification review recorded: {args.row_classification_review_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.allow_partial_extraction_run_dir:
        validate_environment_path(
            environment, args.allow_partial_extraction_run_dir,
            purpose="Allow-partial-extraction run directory",
        )
        summary = write_allow_partial_extraction(
            args.allow_partial_extraction_run_dir,
            decision=args.allow_partial_extraction_decision,
            page_number=3,
            band_id="page-0003-table-band-0001",
        )
        print(f"Allow-partial-extraction recorded: {args.allow_partial_extraction_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.layer_e_extract_run_dir:
        validate_environment_path(
            environment, args.layer_e_extract_run_dir, purpose="Layer E extraction run directory"
        )
        summary = run_layer_e_partial_extraction(
            args.layer_e_extract_run_dir, page_number=3, band_id="page-0003-table-band-0001"
        )
        print(f"Layer E partial extraction: {args.layer_e_extract_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary.get("status") == "ok" else 1
    if args.line_items_review_run_dir:
        validate_environment_path(
            environment, args.line_items_review_run_dir, purpose="Line-items review run directory"
        )
        summary = write_line_items_review_decision(
            args.line_items_review_run_dir, page_number=3, band_id="page-0003-table-band-0001"
        )
        print(f"Line-items review recorded: {args.line_items_review_run_dir}")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.product_matching_readiness_run_dir:
        validate_environment_path(
            environment,
            args.product_matching_readiness_run_dir,
            purpose="Product-matching readiness run directory",
        )
        readiness = validate_product_matching_readiness(
            args.product_matching_readiness_run_dir, page_number=3, band_id="page-0003-table-band-0001"
        )
        tables_dir = args.product_matching_readiness_run_dir / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)
        build_product_matching_readiness_markdown(
            tables_dir / "product_matching_readiness.md", readiness
        )
        print(f"Product matching readiness checked: {args.product_matching_readiness_run_dir}")
        print(json.dumps(readiness, ensure_ascii=False, indent=2))
        return 0 if readiness.get("status") == "ok" else 1
    if args.line_items_preview_run_dir:
        validate_environment_path(
            environment, args.line_items_preview_run_dir, purpose="Line-items preview run directory"
        )
        content = run_line_items_preview(args.line_items_preview_run_dir, page_number=3)
        preview_path = args.line_items_preview_run_dir / "tables" / "table_line_items_preview.md"
        print(f"Preview written: {preview_path}")
        print()
        print(content)
        return 0
    if args.extraction_diagnostic_run_dir:
        validate_environment_path(
            environment, args.extraction_diagnostic_run_dir,
            purpose="Extraction diagnostic run directory",
        )
        content = run_extraction_diagnostic(args.extraction_diagnostic_run_dir, page_number=3)
        diag_path = args.extraction_diagnostic_run_dir / "tables" / "extraction_diagnostic.md"
        print(f"Diagnostic written: {diag_path}")
        print()
        print(content)
        return 0
    input_path = args.input or Path(env_config["inbound_dir"])
    pdfs = discover_pdfs(input_path)
    if not pdfs:
        print(f"No PDF files found at {input_path}", file=sys.stderr)
        return 2
    out_root = (args.out or Path(env_config["out_dir"])).resolve()
    validate_environment_path(environment, out_root, purpose="Output root")
    out_root.mkdir(parents=True, exist_ok=True)
    run_dirs = []
    for pdf in pdfs:
        try:
            run_dirs.append(process_pdf(pdf, out_root, args.dpi, args.openai, args.openai_model, args.cpu_fast))
        except Exception as exc:
            failed_dir = out_root / slug_for_pdf(pdf)
            failed_dir.mkdir(parents=True, exist_ok=True)
            write_json(
                failed_dir / "fatal_error.json",
                {"pdf": str(pdf.resolve()), "error": str(exc), "traceback": traceback.format_exc(), "created_at": now_iso()},
            )
            print(f"Failed {pdf}: {exc}", file=sys.stderr)
    print("Run directories:")
    for run_dir in run_dirs:
        print(run_dir)
    return 0 if run_dirs else 1


if __name__ == "__main__":
    raise SystemExit(main())
