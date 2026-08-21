from __future__ import annotations

import base64
import binascii
import importlib.resources
import json
import mimetypes
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .ada_automation import SaveAuthorization, SubprocessAdaDriver
from .config import repository_root
from .errors import DomainError
from .service import Application


def make_handler(app: Application):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OCRInboundStaging/0.1"

        def _json(self, payload, status=200):
            data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data)

        def _resource(self, name: str):
            resource = importlib.resources.files("ocr_inbound").joinpath("web_static", name)
            data = resource.read_bytes(); mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self.send_response(200); self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or "javascript" in mime else "")); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def _body(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > 50 * 1024 * 1024:
                raise DomainError("REQUEST_TOO_LARGE", "Request body exceeds 50 MiB")
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

        def _require_admin(self, *, csrf=False):
            if not app.is_admin or self.headers.get("X-OCR-Actor") != app.actor.actor_id:
                raise DomainError("ADMIN_REQUIRED", "Authenticated admin access required")
            if csrf and self.headers.get("X-CSRF-Token") != app.csrf_token:
                raise DomainError("CSRF_INVALID", "Valid CSRF token required")

        def do_GET(self):  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/": return self._resource("index.html")
                if parsed.path == "/static/app.css": return self._resource("app.css")
                if parsed.path == "/static/app.js": return self._resource("app.js")
                if parsed.path == "/api/health": return self._json(app.system_health())
                if parsed.path == "/api/documents": return self._json(app.repository.list_documents())
                if parsed.path == "/api/workspace": return self._json(app.workspace(parse_qs(parsed.query).get("document_id", [""])[0]))
                if parsed.path == "/api/admin/product-review":
                    self._require_admin()
                    return self._json(app.product_review.queue(parse_qs(parsed.query).get("document_id", [""])[0]))
                if parsed.path == "/api/admin/product-review/exceptions":
                    self._require_admin()
                    return self._json(app.product_review.exceptions(parse_qs(parsed.query).get("document_id", [""])[0]))
                if parsed.path == "/api/admin/product-master/search":
                    self._require_admin()
                    return self._json(app.product_review.search_master(parse_qs(parsed.query).get("q", [""])[0]))
                if parsed.path == "/api/admin/session":
                    self._require_admin()
                    return self._json({"actor_id": app.actor.actor_id, "csrf_token": app.csrf_token, "role": "ADMIN"})
                if parsed.path == "/api/source":
                    if not app.is_admin or parse_qs(parsed.query).get("token", [""])[0] != app.csrf_token:
                        raise DomainError("SOURCE_ACCESS_DENIED", "Authorized review image token required")
                    document = app.repository.get_document(parse_qs(parsed.query).get("document_id", [""])[0])
                    source = app.product_review.source_path(document["id"])
                    data = source.read_bytes(); mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
                    self.send_response(200); self.send_header("Content-Type", mime); self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'none'; object-src 'none'; sandbox"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
                self.send_error(404)
            except DomainError as exc: self._json(exc.as_dict(), 400)
            except Exception: self._json({"code":"INTERNAL_ERROR","message":"Unexpected local server failure"}, 500)

        def do_POST(self):  # noqa: N802
            try:
                body = self._body(); path = urlparse(self.path).path
                if path == "/api/admin/product-review/decision":
                    self._require_admin(csrf=True)
                    return self._json(app.product_review.decide(body, app.actor))
                if path == "/api/admin/product-review/alias/activate":
                    self._require_admin(csrf=True)
                    return self._json(app.repository.approve_alias(body["alias_id"], app.actor))
                if path == "/api/golden":
                    fixture = body["fixture"]; root = repository_root()/"tests"/"fixtures"/"ocr_top3"/fixture
                    result = app.import_artifact(root/"invoice.svg", root/"artifact.json"); document_id=result["document"]["id"]
                    if not result["duplicate"]: app.generate_predictions(document_id)
                    return self._json({"document_id":document_id,"duplicate":result["duplicate"]})
                if path == "/api/import":
                    try:
                        source_bytes = base64.b64decode(body["source_base64"], validate=True)
                    except (KeyError, ValueError, binascii.Error) as exc:
                        raise DomainError("SOURCE_ENCODING_INVALID", "Uploaded source is not valid base64") from exc
                    result = app.import_uploaded_artifact(body["source_name"], source_bytes, body["artifact"])
                    document_id = result["document"]["id"]
                    if not result["duplicate"]: app.generate_predictions(document_id)
                    return self._json({"document_id":document_id,"duplicate":result["duplicate"]})
                if path == "/api/review/header": return self._json(app.repository.review_header(body["document_id"],body["field_name"],body["final_value"],body["action"],body.get("error_category"),int(body.get("duration_ms",0)),app.actor,"web"))
                if path == "/api/review/product": return self._json(app.review_product(body["document_id"],body["line_id"],body["product_code"],body["unit_code"],action=body["action"],error_category=body.get("error_category"),duration_ms=int(body.get("duration_ms",0))))
                if path == "/api/review/value": return self._json(app.review_line_value(body["document_id"],body["line_id"],body["field_name"],body["final_value"],action=body["action"],error_category=body.get("error_category"),duration_ms=int(body.get("duration_ms",0))))
                if path == "/api/review/bulk": return self._json(app.bulk_confirm_products(body["document_id"],body["line_ids"],duration_ms=int(body.get("duration_ms",0))))
                if path == "/api/ready": return self._json(app.mark_ready(body["document_id"]))
                if path == "/api/ada/draft":
                    if body["driver"] == "FAKE":
                        driver = SubprocessAdaDriver.fake()
                    else:
                        replay = json.loads(importlib.resources.files("ocr_inbound").joinpath("resources/ada_replay_happy.json").read_text(encoding="utf-8"))
                        driver = SubprocessAdaDriver.replay_payload(replay)
                    return self._json(app.automation.start_draft(body["document_id"],app.actor,driver))
                if path == "/api/ada/authorize": return self._json(app.automation.authorize_save(body["run_id"],app.actor).__dict__)
                if path == "/api/ada/save": return self._json(app.automation.save_simulated(SaveAuthorization(body["run_id"],body["token"],app.actor.actor_id,"client-bound"),app.actor))
                self.send_error(404)
            except DomainError as exc: self._json(exc.as_dict(), 400)
            except Exception: self._json({"code":"INTERNAL_ERROR","message":"Unexpected local server failure"}, 500)

        def log_message(self, fmt, *args):
            return
    return Handler


def serve(app: Application, host: str = "127.0.0.1", port: int = 8876, open_browser: bool = True) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise DomainError("NETWORK_BIND_FORBIDDEN", "Staging UI may bind to loopback only")
    server = HTTPServer((host, port), make_handler(app))
    url = f"http://{host}:{port}/"
    print(f"OCR Inbound staging UI: {url}")
    print(app.profile.badge)
    if open_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
