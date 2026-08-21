from __future__ import annotations

import json
import importlib.resources
from dataclasses import dataclass
from pathlib import Path

from .ada_automation import AdaOrchestrator, SubprocessAdaDriver
from .ada_read import AdaReferenceCache
from .artifacts import FilesystemArtifactStore
from .config import AppProfile, build_profile, repository_root
from .db import Repository, new_id
from .errors import DomainError
from .identity import IdentityProvider, StagingIdentityProvider
from .matching import ProductMatcher
from .ocr_adapter import ExistingOcrPipelineAdapter, VersionedOcrArtifactImporter
from .product_review import ProductReviewService
from .structured_log import StructuredLogger
from .validation import InvoiceValidationService


@dataclass
class Application:
    profile: AppProfile
    identity: IdentityProvider
    repository: Repository
    artifacts: FilesystemArtifactStore
    cache: AdaReferenceCache
    matcher: ProductMatcher
    validator: InvoiceValidationService
    automation: AdaOrchestrator
    ocr_pipeline: ExistingOcrPipelineAdapter
    ocr_importer: VersionedOcrArtifactImporter
    logger: StructuredLogger
    startup_recovery: dict
    is_admin: bool = False
    csrf_token: str = ""

    @classmethod
    def bootstrap(cls, *, environment: str = "staging", data_root: Path | None = None, reviewer_id: str = "staging-reviewer", is_admin: bool = False) -> "Application":
        profile = build_profile(environment, data_root)
        if environment != "staging":
            raise DomainError("PRODUCTION_ACTIVATION_BLOCKED", "This build goal authorizes staging only")
        identity = StagingIdentityProvider(reviewer_id)
        repository = Repository(profile)
        repository.migrate()
        startup_recovery = repository.recover_startup_orphans(identity.current_actor())
        artifacts = FilesystemArtifactStore(profile)
        cache = AdaReferenceCache(profile)
        if not cache.path.exists():
            fixture = json.loads(importlib.resources.files("ocr_inbound").joinpath("resources/ada_fixture.json").read_text(encoding="utf-8"))
            cache.refresh_from_fixture(fixture)
        matcher = ProductMatcher(repository, cache)
        validator = InvoiceValidationService(repository, cache)
        logger = StructuredLogger(profile.logs / "application.ndjson")
        automation = AdaOrchestrator(profile, repository, artifacts, validator)
        import secrets
        return cls(profile, identity, repository, artifacts, cache, matcher, validator, automation, ExistingOcrPipelineAdapter(), VersionedOcrArtifactImporter(), logger, startup_recovery, is_admin, secrets.token_urlsafe(24))

    @property
    def product_review(self):
        return ProductReviewService(self)

    @property
    def actor(self):
        return self.identity.current_actor()

    def import_artifact(self, source: Path, artifact_contract: Path) -> dict:
        correlation_id = new_id("corr")
        stored = self.artifacts.store_source(source)
        artifact = self.ocr_importer.load_fixture_contract(artifact_contract)
        return self._import_stored(source.name, stored.sha256, stored.relative_path, artifact, correlation_id)

    def import_uploaded_artifact(self, source_name: str, source_bytes: bytes, artifact: dict) -> dict:
        correlation_id = new_id("corr")
        self.ocr_importer.validate(artifact)
        stored = self.artifacts.store_source_bytes(source_name, source_bytes)
        return self._import_stored(source_name, stored.sha256, stored.relative_path, artifact, correlation_id)

    def _import_stored(self, source_name: str, source_sha256: str, source_artifact_path: str, artifact: dict, correlation_id: str) -> dict:
        existing = self.repository.get_document_by_hash(source_sha256)
        if existing:
            self.repository.append_audit(self.actor.actor_id, "DUPLICATE_FILE_OPEN_EXISTING", "document", existing["id"], correlation_id, {"sha256": source_sha256})
            return {"document": existing, "duplicate": True}
        document = self.repository.create_document(source_filename=source_name, source_sha256=source_sha256, source_artifact_path=source_artifact_path, actor=self.actor, correlation_id=correlation_id)
        self.repository.import_ocr_projection(document["id"], artifact, self.actor, correlation_id)
        self.logger.emit(event="OCR_ARTIFACT_IMPORTED", severity="INFO", correlation_id=correlation_id, document_id=document["id"], actor_id=self.actor.actor_id, detail={"contract_version": artifact["contract_version"], "ocr_run_id": artifact["ocr_run_id"]})
        return {"document": self.repository.get_document(document["id"]), "duplicate": False}

    def generate_predictions(self, document_id: str) -> list[dict]:
        document = self.repository.get_document(document_id)
        versions = {"contract": document["ocr_contract_version"], "run_id": document["ocr_run_id"]}
        predictions = []
        for line in self.repository.list_lines(document_id):
            predictions.append(self.matcher.predict_and_persist(document, line, versions))
        return predictions

    def confirm_headers(self, document_id: str, *, duration_ms: int = 250) -> list[dict]:
        events = []
        for field in self.repository.list_fields(document_id):
            events.append(self.repository.review_header(document_id, field["field_name"], json.loads(field["final_value_json"]), "CONFIRM", None, duration_ms, self.actor, new_id("corr")))
        return events

    def review_product(self, document_id: str, line_id: str, product_code: str, unit_code: str, *, action: str, error_category: str | None = None, duration_ms: int = 500) -> dict:
        if self.cache.get_product(product_code) is None:
            raise DomainError("PRODUCT_OUTSIDE_MASTER", "Product decisions must select an active ADA master product")
        return self.repository.review_product(document_id, line_id, product_code, unit_code, action, error_category, duration_ms, self.actor, new_id("corr"))

    def review_line_value(self, document_id: str, line_id: str, field_name: str, final_value, *, action: str, error_category: str | None = None, duration_ms: int = 500) -> dict:
        return self.repository.review_line_value(document_id, line_id, field_name, final_value, action, error_category, duration_ms, self.actor, new_id("corr"))

    def bulk_confirm_products(self, document_id: str, line_ids: list[str], *, duration_ms: int = 750) -> list[dict]:
        validation = self.validator.validate(document_id)
        blocked = {issue.target_id for issue in validation.issues if issue.target_type == "LINE" and issue.code != "LINE_UNREVIEWED"}
        if blocked.intersection(line_ids):
            raise DomainError("BULK_CONFIRM_INELIGIBLE", "Bulk confirm includes a line with a blocking validation issue")
        return self.repository.bulk_confirm_products(document_id, line_ids, duration_ms, self.actor, new_id("corr"))

    def mark_ready(self, document_id: str) -> dict:
        validation = self.validator.validate(document_id)
        if not validation.ready:
            raise DomainError("READY_VALIDATION_FAILED", "Document has blocking issues", detail=validation.as_dict())
        self.repository.set_ready(document_id, validation.snapshot_hash, self.actor, new_id("corr"))
        return {"document": self.repository.get_document(document_id), "validation": validation.as_dict()}

    def workspace(self, document_id: str) -> dict:
        document = self.repository.get_document(document_id)
        fields = self.repository.list_fields(document_id)
        lines = self.repository.list_lines(document_id)
        return {
            "document": document,
            "fields": [{**field, "predicted_value": json.loads(field["predicted_value_json"]), "final_value": json.loads(field["final_value_json"]), "evidence": json.loads(field["evidence_json"])} for field in fields],
            "lines": [{**line, "evidence": json.loads(line["evidence_json"])} for line in lines],
            "predictions": self.repository.list_predictions(document_id),
            "review_events": self.repository.list_review_events(document_id),
            "validation": self.validator.validate(document_id).as_dict(),
        }

    def run_golden(self, fixture_name: str, *, driver_kind: str = "FAKE") -> dict:
        fixture_root = repository_root() / "tests" / "fixtures" / "ocr_top3" / fixture_name
        imported = self.import_artifact(fixture_root / "invoice.svg", fixture_root / "artifact.json")
        if imported["duplicate"]:
            raise DomainError("GOLDEN_DUPLICATE", "Golden fixture already exists in this data root")
        document_id = imported["document"]["id"]
        predictions = self.generate_predictions(document_id)
        self.confirm_headers(document_id)
        expected = json.loads((fixture_root / "expected_review.json").read_text(encoding="utf-8"))
        lines = self.repository.list_lines(document_id)
        for line, prediction in zip(lines, predictions):
            correction = expected.get("line_corrections", {}).get(str(line["sequence"]))
            if correction:
                self.review_line_value(document_id, line["id"], "quantity", correction["quantity"], action="CORRECT", error_category="QUANTITY_EXTRACTION_ERROR")
                self.review_product(document_id, line["id"], correction["product_code"], correction["unit_code"], action="CORRECT", error_category=correction["error_category"])
            else:
                if not prediction["product_code"] or not prediction["unit_code"]:
                    raise DomainError("GOLDEN_PREDICTION_UNRESOLVED", f"Fixture line {line['sequence']} did not resolve")
                self.review_product(document_id, line["id"], prediction["product_code"], prediction["unit_code"], action="CONFIRM")
        ready = self.mark_ready(document_id)
        if driver_kind == "FAKE":
            driver = SubprocessAdaDriver.fake()
        elif driver_kind == "REPLAY":
            driver = SubprocessAdaDriver.replay(repository_root() / "tests" / "fixtures" / "ada_replay" / "happy.json")
        else:
            raise DomainError("DRIVER_UNSUPPORTED", "Only Fake/Replay are enabled")
        run = self.automation.start_draft(document_id, self.actor, driver)
        authorization = self.automation.authorize_save(run["id"], self.actor)
        receipt = self.automation.save_simulated(authorization, self.actor)
        return {"fixture": fixture_name, "document_id": document_id, "ready_snapshot": ready["validation"]["snapshot_hash"], "driver": driver.kind, "receipt": receipt, "metrics": self.repository.metrics()}

    def system_health(self) -> dict:
        return {
            "status": "ok" if self.repository.integrity_check() == "ok" and self.cache.health()["integrity"] == "ok" else "degraded",
            "environment": self.profile.environment, "badge": self.profile.badge, "app_version": "0.1.0", "schema_version": 1,
            "db_integrity": self.repository.integrity_check(), "ada_cache": self.cache.health(),
            "live_ada_enabled": self.profile.live_ada_enabled, "live_adacc_enabled": self.profile.live_adacc_enabled,
            "production_save_enabled": self.profile.production_save_enabled, "target_allowlist": list(self.profile.target_allowlist),
            "authentication": self.actor.authentication_label, "actor_id": self.actor.actor_id,
            "startup_recovery": self.startup_recovery, "metrics": self.repository.metrics(),
        }
