#!/usr/bin/env python
"""Build ocr_selected_pages.json from an existing OCR pipeline run output.

Usage:
    python build_selected_pages_json.py --run-dir <path> [--out ocr_selected_pages.json]

The run directory must be a completed (or partially completed) output from
ocr_feasibility.py. This script reads the EasyOCR, Tesseract, PaddleOCR, and
native text outputs and synthesises per-page text and confidence.

The source_page_labels below must match the original document page numbers that
were extracted into this filtered PDF.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SOURCE_PAGE_LABELS = ["13", "14", "15", "16", "19", "23", "29", "30", "31", "48", "49", "52", "71"]

POOR_CONFIDENCE_THRESHOLD = 0.50


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip()


def easyocr_page_text_and_confidence(run_dir: Path, page_number: int) -> Tuple[str, Optional[float]]:
    """Return (text, avg_confidence) from EasyOCR for the given 1-based page number."""
    json_path = run_dir / "ocr" / "easyocr" / f"page-{page_number:04d}.json"
    txt_path = run_dir / "ocr" / "easyocr" / f"page-{page_number:04d}.txt"
    rows = read_json(json_path, [])
    if rows:
        confidences = [float(row.get("confidence", 0)) for row in rows if row.get("confidence") is not None]
        lines = [row.get("text", "") for row in rows if row.get("text")]
        text = "\n".join(lines)
        avg_conf = sum(confidences) / len(confidences) if confidences else None
        return text, avg_conf
    text = read_text(txt_path)
    return text, None


def tesseract_best_page_text_and_confidence(run_dir: Path, page_number: int) -> Tuple[str, Optional[float]]:
    """Return (text, avg_confidence) from the best Tesseract TSV for the page."""
    tess_dir = run_dir / "ocr" / "tesseract"
    best_path: Optional[Path] = None
    best_score: Optional[float] = None
    for tsv_path in sorted(tess_dir.glob(f"page-{page_number:04d}_*.tsv")):
        confidences: List[float] = []
        try:
            with tsv_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    text = (row.get("text") or "").strip()
                    conf_raw = row.get("conf", "")
                    if not text or not conf_raw or conf_raw == "-1":
                        continue
                    try:
                        confidences.append(float(conf_raw))
                    except ValueError:
                        pass
        except Exception:
            continue
        if not confidences:
            continue
        score = sum(confidences) / len(confidences)
        if best_score is None or score > best_score:
            best_path = tsv_path
            best_score = score
    if not best_path:
        txt_path = tess_dir / f"page-{page_number:04d}_original_psm-3.stdout.txt"
        if txt_path.exists():
            return read_text(txt_path), None
        return "", None
    stem = best_path.stem
    txt_path = best_path.with_suffix(".stdout.txt")
    if not txt_path.exists():
        return "", best_score
    return read_text(txt_path), best_score / 100.0 if best_score is not None else None


def paddle_page_text_and_confidence(run_dir: Path, page_number: int) -> Tuple[str, Optional[float]]:
    """Return (text, avg_confidence) from the best PaddleOCR result for the page."""
    paddle_dir = run_dir / "ocr" / "paddle"
    best_text = ""
    best_conf: Optional[float] = None
    for lang in ("th", "en"):
        json_path = paddle_dir / f"page-{page_number:04d}_{lang}.json"
        rows = read_json(json_path, [])
        if not rows:
            continue
        confs = [float(r.get("confidence", 0)) for r in rows if r.get("confidence") is not None]
        lines = [r.get("text", "") for r in rows if r.get("text")]
        avg_conf = sum(confs) / len(confs) if confs else None
        if avg_conf is not None and (best_conf is None or avg_conf > best_conf):
            best_text = "\n".join(lines)
            best_conf = avg_conf
    return best_text, best_conf


def native_page_text(run_dir: Path, page_number: int) -> str:
    txt_path = run_dir / "ocr" / "native" / f"page-{page_number:04d}.txt"
    return read_text(txt_path)


def fused_page_text_and_confidence(run_dir: Path, page_number: int) -> Tuple[str, Optional[float]]:
    """Read fused_regions.json and reconstruct per-page text in reading order."""
    fused_path = run_dir / "fusion" / "fused_regions.json"
    all_regions = read_json(fused_path, [])
    page_regions = [r for r in all_regions if r.get("page") == page_number]
    if not page_regions:
        return "", None
    page_regions.sort(key=lambda r: (r.get("bbox", [0, 0, 0, 0])[1], r.get("bbox", [0, 0, 0, 0])[0]))
    lines: List[str] = []
    confidences: List[float] = []
    for region in page_regions:
        text = region.get("normalized_candidate_text") or ""
        if text:
            lines.append(text)
        for candidate in region.get("raw_candidates", {}).values():
            conf = candidate.get("confidence")
            if conf is not None:
                try:
                    conf_f = float(conf)
                    if conf_f > 1.0:
                        conf_f /= 100.0
                    confidences.append(conf_f)
                except (TypeError, ValueError):
                    pass
    text = "\n".join(lines)
    avg_conf = sum(confidences) / len(confidences) if confidences else None
    return text, avg_conf


def image_to_data_url(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{data}"
    except Exception:
        return ""


def build_page_entry(
    run_dir: Path,
    page_number: int,
    source_page_label: str,
    include_image: bool,
) -> Dict[str, Any]:
    fused_text, fused_conf = fused_page_text_and_confidence(run_dir, page_number)
    easy_text, easy_conf = easyocr_page_text_and_confidence(run_dir, page_number)
    tess_text, tess_conf = tesseract_best_page_text_and_confidence(run_dir, page_number)
    paddle_text, paddle_conf = paddle_page_text_and_confidence(run_dir, page_number)
    native_text = native_page_text(run_dir, page_number)

    if fused_text:
        primary_text = fused_text
        primary_conf = fused_conf
        primary_engine = "fusion"
    elif easy_text:
        primary_text = easy_text
        primary_conf = easy_conf
        primary_engine = "easyocr"
    elif paddle_text:
        primary_text = paddle_text
        primary_conf = paddle_conf
        primary_engine = "paddleocr"
    elif tess_text:
        primary_text = tess_text
        primary_conf = tess_conf
        primary_engine = "tesseract"
    elif native_text:
        primary_text = native_text
        primary_conf = None
        primary_engine = "native"
    else:
        primary_text = ""
        primary_conf = None
        primary_engine = "none"

    if primary_conf is not None and primary_conf > 1.0:
        primary_conf = primary_conf / 100.0

    entry: Dict[str, Any] = {
        "source_page_label": source_page_label,
        "text": primary_text,
        "confidence": round(primary_conf, 4) if primary_conf is not None else None,
        "primary_engine": primary_engine,
        "engine_outputs": {},
        "status": "ok" if primary_text else "no_text",
    }

    if easy_conf is not None and easy_conf > 1.0:
        easy_conf = easy_conf / 100.0
    if tess_conf is not None and tess_conf > 1.0:
        tess_conf = tess_conf / 100.0

    entry["engine_outputs"]["easyocr"] = {
        "text": easy_text,
        "confidence": round(easy_conf, 4) if easy_conf is not None else None,
    }
    entry["engine_outputs"]["tesseract"] = {
        "text": tess_text,
        "confidence": round(tess_conf, 4) if tess_conf is not None else None,
    }
    entry["engine_outputs"]["paddleocr"] = {
        "text": paddle_text,
        "confidence": round(paddle_conf, 4) if paddle_conf is not None else None,
    }
    entry["engine_outputs"]["native"] = {
        "text": native_text,
        "confidence": None,
    }

    if include_image:
        image_path = run_dir / "pages" / f"page-{page_number:04d}.png"
        entry["image_data_url"] = image_to_data_url(image_path)

    return entry


def run_dir_for_pdf_slug(staging_root: Path, slug_fragment: str) -> Optional[Path]:
    for candidate in sorted(staging_root.iterdir()):
        if candidate.is_dir() and slug_fragment in candidate.name:
            return candidate
    return None


def build_selected_pages_json(
    run_dir: Path,
    output_path: Path,
    source_page_labels: List[str],
    include_images: bool,
) -> Dict[str, Any]:
    page_count = len(source_page_labels)
    output: Dict[str, Any] = {}
    confidences: List[float] = []
    poor_pages: List[str] = []
    engines_used = set()

    for idx, label in enumerate(source_page_labels, 1):
        key = f"page_{idx}"
        entry = build_page_entry(run_dir, idx, label, include_images)
        output[key] = entry
        conf = entry.get("confidence")
        if conf is not None:
            confidences.append(conf)
            if conf < POOR_CONFIDENCE_THRESHOLD:
                poor_pages.append(f"page_{idx} (source {label}, conf={conf:.3f})")
        engine = entry.get("primary_engine", "none")
        if engine not in ("none",):
            engines_used.add(engine)

    avg_conf = sum(confidences) / len(confidences) if confidences else None

    summary = {
        "pages_processed": page_count,
        "engines_used": sorted(engines_used),
        "average_confidence": round(avg_conf, 4) if avg_conf is not None else None,
        "poor_quality_pages": poor_pages,
        "run_dir": str(run_dir),
        "source_page_labels": source_page_labels,
    }
    output["_summary"] = summary

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ocr_selected_pages.json from a pipeline run directory.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Path to the OCR pipeline run directory.")
    parser.add_argument("--out", type=Path, default=Path("ocr_selected_pages.json"), help="Output JSON path.")
    parser.add_argument("--no-images", action="store_true", help="Skip embedding base64 page images.")
    args = parser.parse_args()
    if not args.run_dir.exists():
        print(f"Run directory not found: {args.run_dir}", file=sys.stderr)
        return 1
    print(f"Reading from: {args.run_dir}")
    summary = build_selected_pages_json(
        run_dir=args.run_dir,
        output_path=args.out,
        source_page_labels=SOURCE_PAGE_LABELS,
        include_images=not args.no_images,
    )
    print(f"Saved: {args.out}")
    print(f"Pages processed: {summary['pages_processed']}")
    print(f"Engines used: {', '.join(summary['engines_used'])}")
    if summary["average_confidence"] is not None:
        print(f"Average confidence: {summary['average_confidence']:.4f}")
    if summary["poor_quality_pages"]:
        print("Poor quality pages:")
        for page in summary["poor_quality_pages"]:
            print(f"  - {page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
