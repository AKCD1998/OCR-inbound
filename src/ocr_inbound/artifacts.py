from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import AppProfile
from .db import canonical_json, now_iso
from .errors import DomainError


@dataclass(frozen=True)
class StoredSource:
    sha256: str
    relative_path: str
    manifest_relative_path: str
    mime_type: str
    byte_size: int


def sniff_mime(path: Path, head: bytes) -> str:
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if b"<svg" in head[:512].lower():
        return "image/svg+xml"
    raise DomainError("SOURCE_TYPE_UNSUPPORTED", "Only PDF or recognized image content can be imported")


class FilesystemArtifactStore:
    def __init__(self, profile: AppProfile) -> None:
        self.profile = profile

    def store_source(self, source: Path) -> StoredSource:
        if not source.is_file():
            raise DomainError("SOURCE_NOT_FOUND", f"Source file not found: {source}")
        digest = hashlib.sha256()
        byte_size = 0
        head = b""
        with source.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                if not head:
                    head = chunk[:512]
                digest.update(chunk)
                byte_size += len(chunk)
        mime_type = sniff_mime(source, head)
        sha256 = digest.hexdigest()
        extension = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/tiff": ".tiff", "image/svg+xml": ".svg"}[mime_type]
        folder = self.profile.artifacts / "sources" / sha256[:2] / sha256
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"original{extension}"
        if not target.exists():
            fd, temp_name = tempfile.mkstemp(prefix="source-", suffix=".tmp", dir=folder)
            try:
                with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
                    shutil.copyfileobj(inp, out)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
            raise DomainError("SOURCE_CHECKSUM_MISMATCH", "Immutable source checksum verification failed")
        manifest = {
            "manifest_version": "source-manifest.v1", "sha256": sha256, "byte_size": byte_size,
            "mime_type": mime_type, "original_name": source.name, "importer_version": "0.1.0", "stored_at": now_iso(),
            "relative_source_path": target.relative_to(self.profile.root).as_posix(),
        }
        manifest_path = folder / "manifest.json"
        self._atomic_json(manifest_path, manifest)
        return StoredSource(sha256, target.relative_to(self.profile.root).as_posix(), manifest_path.relative_to(self.profile.root).as_posix(), mime_type, byte_size)

    def store_source_bytes(self, original_name: str, payload: bytes) -> StoredSource:
        if not payload:
            raise DomainError("SOURCE_EMPTY", "Source file is empty")
        if len(payload) > 32 * 1024 * 1024:
            raise DomainError("SOURCE_TOO_LARGE", "Source file exceeds the 32 MiB staging limit")
        clean_name = Path(original_name).name
        if not clean_name or clean_name != original_name:
            raise DomainError("SOURCE_NAME_INVALID", "Source filename must not contain a path")
        mime_type = sniff_mime(Path(clean_name), payload[:512])
        sha256 = hashlib.sha256(payload).hexdigest()
        extension = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/tiff": ".tiff", "image/svg+xml": ".svg"}[mime_type]
        folder = self.profile.artifacts / "sources" / sha256[:2] / sha256
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"original{extension}"
        if not target.exists():
            fd, temp_name = tempfile.mkstemp(prefix="source-", suffix=".tmp", dir=folder)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(payload)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
            raise DomainError("SOURCE_CHECKSUM_MISMATCH", "Immutable source checksum verification failed")
        manifest = {
            "manifest_version": "source-manifest.v1", "sha256": sha256, "byte_size": len(payload),
            "mime_type": mime_type, "original_name": clean_name, "importer_version": "0.1.0", "stored_at": now_iso(),
            "relative_source_path": target.relative_to(self.profile.root).as_posix(),
        }
        manifest_path = folder / "manifest.json"
        self._atomic_json(manifest_path, manifest)
        return StoredSource(sha256, target.relative_to(self.profile.root).as_posix(), manifest_path.relative_to(self.profile.root).as_posix(), mime_type, len(payload))

    def write_json_artifact(self, relative_path: str, payload: dict) -> str:
        target = self.profile.assert_within_root(self.profile.root / relative_path, "Artifact")
        self._atomic_json(target, payload)
        return target.relative_to(self.profile.root).as_posix()

    def read_json_artifact(self, relative_path: str) -> dict:
        target = self.profile.assert_within_root(self.profile.root / relative_path, "Artifact")
        return json.loads(target.read_text(encoding="utf-8"))

    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
