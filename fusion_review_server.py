#!/usr/bin/env python
"""Lightweight local review server for OCR fusion outputs."""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from ocr_environment import environment_config, load_dotenv, resolve_environment_name, validate_environment_path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "region_id",
        "page",
        "selected_candidate_engine",
        "selected_candidate_text",
        "review_status",
        "review_notes",
        "saved_at",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def confidence_to_unit(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    if numeric > 1.0:
        numeric = numeric / 100.0
    return max(0.0, min(1.0, numeric))


class ReviewApp:
    def __init__(self, run_dir: Path, environment: str) -> None:
        self.environment = resolve_environment_name(environment)
        self.environment_config = environment_config(self.environment)
        self.run_dir = run_dir
        self.pages_dir = run_dir / "pages"
        self.fusion_dir = run_dir / "fusion"
        self.tables_dir = run_dir / "tables"
        self.static_dir = Path(__file__).resolve().parent / "fusion_review_ui"
        self.fused_regions = read_json(self.fusion_dir / "fused_regions.json", [])
        self.zoned_regions = read_json(self.fusion_dir / "zoned_regions_v2.json", read_json(self.fusion_dir / "zoned_regions.json", []))
        self.conflicts = read_json(self.fusion_dir / "conflicts.json", [])
        self.unique_regions = read_json(self.fusion_dir / "unique_regions.json", [])
        self.table_bands_payload = read_json(self.tables_dir / "table_bands.json", {"bands": []})
        self.table_bands = self.table_bands_payload.get("bands", [])
        self.table_rows_payload = read_json(self.tables_dir / "table_rows.json", {"rows": []})
        self.table_rows = self.table_rows_payload.get("rows", [])
        self.review_json_path = self.fusion_dir / "review_decisions.json"
        self.review_csv_path = self.fusion_dir / "review_decisions.csv"
        self.summary = self._build_summary()

    def _build_summary(self) -> Dict[str, Any]:
        page_numbers = sorted({int(region.get("page", 0)) for region in self.fused_regions if region.get("page")})
        classifications = sorted({region.get("classification", "") for region in self.fused_regions if region.get("classification")})
        categories = sorted({cat for region in self.fused_regions for cat in region.get("category_labels", [])})
        engines = sorted({engine for region in self.fused_regions for engine in region.get("source_engines_present", [])})
        zones = sorted({region.get("zone", "") for region in self.zoned_regions if region.get("zone")})
        suggested_zones = sorted({region.get("suggested_zone", "") for region in self.zoned_regions if region.get("suggested_zone")})
        pages = []
        for page_number in page_numbers:
            image_path = self.pages_dir / f"page-{page_number:04d}.png"
            pages.append(
                {
                    "page": page_number,
                    "image_url": f"/api/page-image?page={page_number}",
                    "width": next((region.get("page_width") for region in self.fused_regions if region.get("page") == page_number), None),
                    "height": next((region.get("page_height") for region in self.fused_regions if region.get("page") == page_number), None),
                    "exists": image_path.exists(),
                }
            )
        return {
            "environment": self.environment,
            "environment_label": self.environment_config["label"],
            "run_dir": str(self.run_dir),
            "generated_at": now_iso(),
            "counts": {
                "fused_regions": len(self.fused_regions),
                "conflicts": len(self.conflicts),
                "unique_regions": len(self.unique_regions),
                "table_bands": len(self.table_bands),
                "table_rows": len(self.table_rows),
            },
            "pages": pages,
            "classifications": classifications,
            "category_labels": categories,
            "engines": engines,
            "zones": zones,
            "suggested_zones": suggested_zones,
        }

    def decision_store(self) -> Dict[str, Any]:
        return read_json(self.review_json_path, {"run_dir": str(self.run_dir), "saved_at": None, "decisions": []})

    def decision_map(self) -> Dict[str, Dict[str, Any]]:
        decisions = self.decision_store().get("decisions", [])
        return {entry["region_id"]: entry for entry in decisions if entry.get("region_id")}

    def save_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        store = self.decision_store()
        decisions = self.decision_map()
        region_id = decision["region_id"]
        decisions[region_id] = {
            "region_id": region_id,
            "page": decision.get("page"),
            "selected_candidate_engine": decision.get("selected_candidate_engine"),
            "selected_candidate_text": decision.get("selected_candidate_text"),
            "review_status": decision.get("review_status"),
            "review_notes": decision.get("review_notes", ""),
            "saved_at": now_iso(),
        }
        rows = sorted(decisions.values(), key=lambda item: (int(item.get("page") or 0), item.get("region_id", "")))
        payload = {"run_dir": str(self.run_dir), "saved_at": now_iso(), "decisions": rows}
        write_json(self.review_json_path, payload)
        write_csv(self.review_csv_path, rows)
        return payload

    def region_payload(self) -> List[Dict[str, Any]]:
        decisions = self.decision_map()
        zones_by_region = {region.get("region_id"): region for region in self.zoned_regions if region.get("region_id")}
        enriched: List[Dict[str, Any]] = []
        for region in self.fused_regions:
            raw_candidates = region.get("raw_candidates", {})
            candidate_confidences = [confidence_to_unit(candidate.get("confidence")) for candidate in raw_candidates.values()]
            candidate_confidences = [value for value in candidate_confidences if value is not None]
            confidence_score = max(candidate_confidences) if candidate_confidences else None
            zone_region = zones_by_region.get(region.get("region_id"), {})
            enriched.append(
                {
                    **region,
                    "zone": zone_region.get("zone", "unknown"),
                    "zone_confidence": zone_region.get("zone_confidence"),
                    "zone_reasons": zone_region.get("zone_reasons", []),
                    "zone_score": zone_region.get("zone_score"),
                    "zone_score_margin": zone_region.get("zone_score_margin"),
                    "zone_rankings": zone_region.get("zone_rankings", []),
                    "why_unknown": zone_region.get("why_unknown", ""),
                    "suggested_zone": zone_region.get("suggested_zone", ""),
                    "confidence_score": confidence_score,
                    "review_decision": decisions.get(region.get("region_id")),
                }
            )
        return enriched


def make_handler(app: ReviewApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FusionReviewHTTP/0.1"

        def _send_json(self, payload: Any, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_file(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                return
            mime_type, _ = mimetypes.guess_type(str(path))
            content = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_file(app.static_dir / "index.html")
                return
            if parsed.path.startswith("/static/"):
                rel = parsed.path.replace("/static/", "", 1)
                self._send_file(app.static_dir / rel)
                return
            if parsed.path == "/api/data":
                self._send_json(
                    {
                        "summary": app.summary,
                        "regions": app.region_payload(),
                        "conflicts": app.conflicts,
                        "unique_regions": app.unique_regions,
                        "table_bands": app.table_bands,
                        "table_bands_payload": app.table_bands_payload,
                        "table_rows": app.table_rows,
                        "table_rows_payload": app.table_rows_payload,
                        "review_decisions": app.decision_store(),
                    }
                )
                return
            if parsed.path == "/api/page-image":
                params = parse_qs(parsed.query)
                try:
                    page_number = int(params.get("page", ["0"])[0])
                except ValueError:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid page")
                    return
                self._send_file(app.pages_dir / f"page-{page_number:04d}.png")
                return
            if parsed.path == "/api/review-decisions":
                self._send_json(app.decision_store())
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/review-decisions":
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
                return
            if not payload.get("region_id"):
                self.send_error(HTTPStatus.BAD_REQUEST, "region_id is required")
                return
            saved = app.save_decision(payload)
            self._send_json(saved, status=200)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the OCR fusion review UI.")
    parser.add_argument("--env", choices=["production", "staging"], help="Environment profile for run-dir and port defaults.")
    parser.add_argument("--run-dir", type=Path, help="Existing run directory containing pages/ and fusion/ outputs.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, help="Port to bind.")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    environment = resolve_environment_name(args.env)
    env_config = environment_config(environment)
    run_dir = (args.run_dir or Path(env_config["run_dir"])).resolve()
    validate_environment_path(environment, run_dir, purpose="Review run directory")
    port = args.port or int(env_config["review_port"])
    app = ReviewApp(run_dir, environment)
    handler = make_handler(app)
    httpd = ThreadingHTTPServer((args.host, port), handler)
    print(f"Fusion review UI: http://{args.host}:{port}")
    print(f"Environment: {env_config['label']}")
    print(f"Run directory: {run_dir}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
