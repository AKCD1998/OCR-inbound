"""Loopback-only final-review HTTP adapter for the Document AI prototype.

The store owns all evidence, revisions, decisions and export admission. This
adapter never starts a model, writes an ERP or turns a proposal into approval.
"""
from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlsplit

STATIC_ROOT = Path(__file__).with_name("static")
CLIENT_HEADER = "final-review-v1"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
_KEY = re.compile(r"^[^/\\\x00-\x1f\x7f]{1,200}$")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' blob: data:; frame-src 'self' blob:; "
    "object-src 'none'; connect-src 'self'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)


class StoreProtocol(Protocol):
    def list_documents(self) -> list[dict]: ...
    def get_document(self, document_id: str) -> dict: ...
    def ingest_source(self, filename: str, content: bytes, media_type: str | None,
                      reviewer: str) -> dict: ...
    def review_row(self, document_id: str, row_id: str, decision: str,
                   corrections: dict, note: str, reviewer: str,
                   expected_revision: int) -> dict: ...
    def history(self, document_id: str) -> list[dict]: ...
    def export_document(self, document_id: str, reviewer: str,
                        completeness_confirmed: bool = False,
                        expected_revision: int | None = None,
                        source_sha256: str | None = None) -> dict: ...
    def add_review_row(self, document_id: str, fields: dict, note: str, reviewer: str,
                       expected_revision: int, page_id: str) -> dict: ...
    def get_asset(self, document_id: str, asset_id: str) -> tuple[Path, str]: ...


class RequestProblem(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _key(value: str) -> str:
    value = unquote(value)
    if value in {".", ".."} or not _KEY.fullmatch(value):
        raise RequestProblem("INVALID_IDENTIFIER", "รหัสรายการไม่ถูกต้อง")
    return value


def _filename(value: str) -> str:
    if not value or len(value) > 240 or any(c in value for c in "/\\\x00\r\n"):
        raise RequestProblem("INVALID_FILENAME", "ชื่อไฟล์ไม่ถูกต้อง")
    if value in {".", ".."} or any(ord(c) < 32 for c in value):
        raise RequestProblem("INVALID_FILENAME", "ชื่อไฟล์ไม่ถูกต้อง")
    return value


def sniff_source(data: bytes) -> str:
    """Validate supported passive formats independently of extension/MIME."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise RequestProblem("UNSUPPORTED_SOURCE", "รองรับไฟล์ PDF, PNG และ JPEG เท่านั้น", 415)


def make_handler(store: StoreProtocol, reviewer: str, *,
                 max_upload_bytes: int = MAX_UPLOAD_BYTES) -> type[BaseHTTPRequestHandler]:
    if not reviewer.strip():
        raise ValueError("A named reviewer is required")

    class Handler(BaseHTTPRequestHandler):
        server_version = "DocumentAIReview/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Original filenames, notes and payloads do not belong in access logs.
            return

        def _check_request_origin(self, *, mutation: bool = False) -> None:
            port = self.server.server_port
            raw_host = self.headers.get("Host", "")
            try:
                host = urlsplit("http://" + raw_host)
                if (host.hostname not in _LOOPBACK or (host.port or 80) != port
                        or host.path or host.query or host.fragment or host.username):
                    raise ValueError("host")
            except ValueError:
                raise RequestProblem("HOST_DENIED", "เปิดหน้านี้ผ่านที่อยู่ในเครื่องเท่านั้น", 403)
            origin = self.headers.get("Origin")
            if origin:
                try:
                    parsed = urlsplit(origin)
                    if (parsed.scheme != "http" or parsed.hostname != host.hostname
                            or (parsed.port or 80) != port or parsed.path not in {"", "/"}
                            or parsed.query or parsed.fragment or parsed.username):
                        raise ValueError("origin")
                except ValueError:
                    raise RequestProblem("ORIGIN_DENIED", "คำขอต้องมาจากหน้ารีวิวในเครื่องเดียวกัน", 403)
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise RequestProblem("ORIGIN_DENIED", "ไม่รับคำขอจากเว็บไซต์อื่น", 403)
            if mutation and self.headers.get("X-Document-AI-Client") != CLIENT_HEADER:
                raise RequestProblem("CLIENT_REQUIRED", "กรุณาส่งคำขอจากหน้ารีวิวนี้", 403)

        def _headers(self, status: int, media_type: str, length: int, *,
                     attachment: str | None = None, embedded_asset: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", _CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'") if embedded_asset else _CSP)
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            if self.close_connection:
                self.send_header("Connection", "close")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
            self.end_headers()

        def _json(self, value: Any, status: int = 200, attachment: str | None = None) -> None:
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(payload), attachment=attachment)
            self.wfile.write(payload)

        def _problem(self, exc: Exception) -> None:
            status = getattr(exc, "status", 500)
            if not isinstance(status, int) or status not in range(400, 600):
                status = 500
            if isinstance(exc, RequestProblem) or (hasattr(exc, "code") and hasattr(exc, "message")):
                value = {"error": {"code": str(exc.code), "message": str(exc.message)}}
            else:
                value = {"error": {"code": "INTERNAL_ERROR", "message": "ดำเนินการไม่สำเร็จ กรุณาตรวจสถานะเอกสารอีกครั้ง"}}
            self.close_connection = True
            self._json(value, status)

        def _body(self, maximum: int) -> bytes:
            if self.headers.get("Transfer-Encoding"):
                raise RequestProblem("LENGTH_REQUIRED", "ต้องระบุขนาดข้อมูล", 411)
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if length < 0:
                raise RequestProblem("LENGTH_REQUIRED", "ต้องระบุขนาดข้อมูล", 411)
            if length > maximum:
                raise RequestProblem("UPLOAD_TOO_LARGE", f"ไฟล์ใหญ่เกินขนาดที่รับได้ ({maximum // 1024 // 1024} MB)", 413)
            if length == 0:
                return b""
            self.connection.settimeout(30)
            payload = self.rfile.read(length)
            if len(payload) != length:
                raise RequestProblem("INCOMPLETE_BODY", "รับข้อมูลไม่ครบ กรุณาส่งใหม่")
            return payload

        def _json_body(self) -> dict:
            if self.headers.get_content_type() != "application/json":
                raise RequestProblem("JSON_REQUIRED", "รูปแบบข้อมูลไม่ถูกต้อง", 415)
            try:
                value = json.loads(self._body(MAX_JSON_BYTES).decode("utf-8"),
                                   parse_constant=lambda _x: (_ for _ in ()).throw(ValueError("nonfinite")))
            except (ValueError, UnicodeError):
                raise RequestProblem("INVALID_JSON", "ข้อมูล JSON ไม่ถูกต้อง")
            if not isinstance(value, dict):
                raise RequestProblem("INVALID_JSON", "ข้อมูลต้องเป็นรายการ JSON")
            return value

        def _parts(self) -> tuple[list[str], dict[str, list[str]]]:
            parsed = urlsplit(self.path)
            return [p for p in parsed.path.split("/") if p], parse_qs(parsed.query)

        def do_GET(self) -> None:
            try:
                self._check_request_origin()
                parts, _query = self._parts()
                if not parts:
                    return self._static("index.html")
                if parts == ['favicon.ico']:
                    return self._headers(204,'image/x-icon',0)
                if len(parts) == 2 and parts[0] == "static" and parts[1] in {"app.js", "app.css"}:
                    return self._static(parts[1])
                if parts == ["api", "config"]:
                    return self._json({"reviewer": reviewer, "max_upload_bytes": max_upload_bytes,
                                       "accepted_media_types": ["application/pdf", "image/png", "image/jpeg"],
                                       "live_erp_writes": False})
                if parts == ["api", "documents"]:
                    return self._json({"documents": store.list_documents()})
                if len(parts) >= 3 and parts[:2] == ["api", "documents"]:
                    doc = _key(parts[2])
                    if len(parts) == 3:
                        return self._json(store.get_document(doc))
                    if len(parts) == 4 and parts[3] == "history":
                        return self._json({"events": store.history(doc)})
                    if len(parts) == 5 and parts[3] == "assets":
                        return self._asset(doc, _key(parts[4]))
                raise RequestProblem("NOT_FOUND", "ไม่พบหน้านี้", 404)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                self._problem(exc)

        def do_POST(self) -> None:
            try:
                self._check_request_origin(mutation=True)
                parts, query = self._parts()
                if parts == ["api", "documents"]:
                    # Consume an admitted, bounded upload before rejecting its
                    # filename. Closing with unread bytes can reset the socket
                    # before Windows clients receive the JSON error response.
                    content = self._body(max_upload_bytes)
                    names = query.get("filename", [])
                    if len(names) != 1:
                        raise RequestProblem("INVALID_FILENAME", "กรุณาระบุชื่อไฟล์หนึ่งชื่อ")
                    name = _filename(names[0])
                    media_type = sniff_source(content)
                    document = store.ingest_source(name, content, media_type, reviewer)
                    return self._json(document, HTTPStatus.ACCEPTED)
                if len(parts) >= 4 and parts[:2] == ["api", "documents"]:
                    doc = _key(parts[2])
                    if len(parts) == 4 and parts[3] == "export":
                        body = self._json_body()
                        if body.get("completeness_confirmed") is not True:
                            raise RequestProblem("COMPLETENESS_REQUIRED", "กรุณายืนยันว่าตรวจเทียบต้นฉบับครบทุกหน้าและไม่มีรายการตกหล่นแล้ว")
                        revision, source_sha = body.get("expected_revision"), body.get("source_sha256")
                        if (type(revision) is not int or revision < 0 or not isinstance(source_sha, str)
                                or not re.fullmatch(r'[0-9a-f]{64}', source_sha)):
                            raise RequestProblem("INVALID_EXPORT_BINDING", "ต้องส่งผลตรวจพร้อมรุ่นข้อมูลและรหัสต้นฉบับที่ตรวจอยู่")
                        output = store.export_document(doc, reviewer, completeness_confirmed=True,
                                                       expected_revision=revision, source_sha256=source_sha)
                        return self._json(output, attachment="erp-reviewed-handoff.json")
                    if len(parts) == 4 and parts[3] == "rows":
                        body = self._json_body()
                        fields, note, revision, page_id = (body.get("fields"), body.get("note"),
                                                          body.get("expected_revision"), body.get("page_id"))
                        if (not isinstance(fields, dict) or not fields or len(fields) > 100
                                or not isinstance(note, str) or not note.strip() or len(note) > 20000
                                or not isinstance(revision, int) or isinstance(revision, bool) or revision < 0
                                or not isinstance(page_id, str)):
                            raise RequestProblem("INVALID_ADDED_ROW", "ระบุหน้า ข้อมูล และเหตุผลของรายการที่เพิ่มให้ครบ")
                        return self._json(store.add_review_row(doc, fields, note, reviewer, revision, _key(page_id)), 201)
                    if len(parts) == 6 and parts[3] == "rows" and parts[5] == "review":
                        row = _key(parts[4])
                        body = self._json_body()
                        decision = body.get("decision")
                        if decision not in {"approve", "correct", "hold"}:
                            raise RequestProblem("INVALID_DECISION", "เลือกยืนยัน แก้ไขและยืนยัน หรือพักรายการ")
                        corrections, note = body.get("corrections", {}), body.get("note", "")
                        revision = body.get("expected_revision")
                        if (not isinstance(corrections, dict) or len(corrections) > 100
                                or not isinstance(note, str) or len(note) > 20000
                                or not isinstance(revision, int) or isinstance(revision, bool) or revision < 0):
                            raise RequestProblem("INVALID_REVIEW", "ข้อมูลผลตรวจไม่ถูกต้อง")
                        result = store.review_row(doc, row, decision, corrections, note, reviewer, revision)
                        return self._json(result)
                raise RequestProblem("NOT_FOUND", "ไม่พบรายการที่ต้องการบันทึก", 404)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                self._problem(exc)

        def _static(self, name: str) -> None:
            path = STATIC_ROOT / name
            payload = path.read_bytes()
            media = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
                     "app.css": "text/css; charset=utf-8"}[name]
            self._headers(200, media, len(payload))
            self.wfile.write(payload)

        def _asset(self, document_id: str, asset_id: str) -> None:
            # Only the store resolves opaque asset IDs; no request path touches disk.
            path, media = store.get_asset(document_id, asset_id)
            path = Path(path)
            if media not in {"application/pdf", "image/png", "image/jpeg"}:
                raise RequestProblem("UNSUPPORTED_ASSET", "ไม่รองรับการเปิดไฟล์ชนิดนี้ในหน้ารีวิว", 415)
            length = path.stat().st_size
            self._headers(200, media, length, embedded_asset=True)
            with path.open("rb") as source:
                while block := source.read(256 * 1024):
                    self.wfile.write(block)

    return Handler


def make_server(store: StoreProtocol, host: str = "127.0.0.1", port: int = 8877,
                reviewer: str = "", *, max_upload_bytes: int = MAX_UPLOAD_BYTES) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("The review prototype may bind only to loopback")
    server = ThreadingHTTPServer((host, port), make_handler(store, reviewer, max_upload_bytes=max_upload_bytes))
    server.daemon_threads = True
    return server


def serve(store: StoreProtocol, host: str = "127.0.0.1", port: int = 8877,
          reviewer: str = "", *, max_upload_bytes: int = MAX_UPLOAD_BYTES) -> None:
    with make_server(store, host, port, reviewer, max_upload_bytes=max_upload_bytes) as server:
        print(f"Document final review: http://127.0.0.1:{server.server_port}")
        try:
            server.serve_forever(poll_interval=.5)
        except KeyboardInterrupt:
            return
