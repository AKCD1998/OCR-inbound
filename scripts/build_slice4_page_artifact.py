"""Build the Slice-4 review artifact from an existing, read-only OCR run."""
from __future__ import annotations

import argparse
import hashlib
import struct
import tempfile
from pathlib import Path

from ocr_inbound.page_extraction import (
    build_page_extraction_bundle,
    extract_page,
    write_page_extraction_bundle,
)
from ocr_inbound.service import Application


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        if stream.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Not a PNG: {path}")
        length = struct.unpack(">I", stream.read(4))[0]
        if stream.read(4) != b"IHDR" or length < 8:
            raise ValueError(f"PNG has no IHDR: {path}")
        return struct.unpack(">II", stream.read(8))


def build(run_root: Path, source: Path, output: Path, pages: list[int]) -> dict:
    extractions = []
    image_refs = {}
    matcher_results = {}
    with tempfile.TemporaryDirectory(prefix="ocr-slice4-matcher-") as temporary:
        app = Application.bootstrap(data_root=Path(temporary), reviewer_id="slice4-read-only")
        for page_number in pages:
            stem = f"page-{page_number:03d}"
            image = run_root / "pages" / f"{stem}.png"
            extraction = extract_page(
                page_number=page_number,
                paddle_json_path=run_root / "ocr" / "paddle_th" / f"{stem}.json",
                tesseract_text_path=run_root / "ocr" / "tesseract" / f"{stem}_psm6.txt",
                image_size=png_size(image),
            )
            # Canonical supplier identity, when the page's own extraction
            # positively confirmed one (see page_extraction.py's
            # `canonical_supplier_code` field) -- NEVER derived here from
            # `page_number`/the source filename. "UNKNOWN" means no
            # supplier-identity contract exists yet for this page's
            # layout; the matcher is given `supplier_code=None` in that
            # case (its own documented behavior for "no supplier
            # context"), and `alias_path_tested=False` is recorded on
            # every row of this page so nothing downstream can claim the
            # exact-supplier-alias path was exercised when it structurally
            # could not have been.
            canonical_supplier_code = extraction.get("canonical_supplier_code", "UNKNOWN")
            alias_path_tested = canonical_supplier_code != "UNKNOWN"
            document = {
                "id": f"SLICE4-PAGE-{page_number}",
                "supplier_code": canonical_supplier_code if alias_path_tested else None,
            }
            for row in extraction["product_rows"]:
                description = row["fields"].get("description")
                text = description["raw_text"] if description else ""
                if not text.strip():
                    matcher_results[(page_number, row["row_index"])] = {
                        "tier": "NOT_EVALUATED",
                        "method": "MISSING_DESCRIPTION",
                        "reason_codes": ["MISSING_FIELD:description"],
                        "candidate_set": [],
                        "proposed_product_code": None,
                        "alias_path_tested": False,
                    }
                    continue
                # Extracted, per-row evidence -- never fabricated when a
                # row's own real OCR evidence does not carry it (e.g. page
                # 58 row 2 has no printed supplier SKU at all; it stays
                # None here, it is never inherited from a sibling row).
                supplier_sku_field = row["fields"].get("supplier_sku")
                supplier_sku = supplier_sku_field["raw_text"] if supplier_sku_field else None
                unit_field = row["fields"].get("unit")
                # `unit_final` is read by the matcher's own
                # `.strip().upper()` normalization (matching.py) -- passed
                # through as-extracted; this script does not re-format it
                # itself, so the matcher's own documented contract is the
                # single source of truth for the canonical unit shape.
                unit_final = unit_field["raw_text"] if unit_field else None
                prediction = app.matcher._predict(
                    document,
                    {
                        "id": f"SLICE4-PAGE-{page_number}-ROW-{row['row_index']}",
                        "supplier_sku": supplier_sku,
                        "description_final": text,
                        "raw_ocr_text": text,
                        "unit_final": unit_final,
                        "evidence_json": "{}",
                    },
                    {"paddle_th": "existing-evidence", "tesseract": "existing-evidence"},
                )
                prediction["alias_path_tested"] = alias_path_tested
                matcher_results[(page_number, row["row_index"])] = prediction
            extractions.append(extraction)
            image_refs[page_number] = f"pages/{stem}.png"

        # The pure matcher boundary above must not create any document rows.
        if app.repository.list_documents():
            raise RuntimeError("Read-only matcher projection unexpectedly persisted data")

    payload = build_page_extraction_bundle(
        source_name=source.name,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        pages=extractions,
        image_refs=image_refs,
        matcher_results=matcher_results,
    )
    write_page_extraction_bundle(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pages", default="5,6,13,14,15,19,30,40,48,58")
    args = parser.parse_args()
    pages = [int(value) for value in args.pages.split(",")]
    payload = build(args.run_root.resolve(), args.source.resolve(), args.output.resolve(), pages)
    print(payload["summary"])


if __name__ == "__main__":
    main()
