CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  environment TEXT NOT NULL CHECK(environment IN ('staging','production')),
  source_filename TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  source_artifact_path TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('NEW','PROCESSING','NEEDS_REVIEW','READY_FOR_ADA','SENDING_TO_ADA','ADA_REVIEW_REQUIRED','COMPLETED','FAILED','CANCELLED')),
  last_stable_status TEXT NOT NULL,
  supplier_code TEXT,
  invoice_number_normalized TEXT,
  invoice_date TEXT,
  grand_total_minor INTEGER,
  duplicate_key TEXT,
  revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
  review_snapshot_hash TEXT,
  ocr_contract_version TEXT,
  ocr_run_id TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(environment, source_sha256)
);
CREATE INDEX idx_documents_business_duplicate ON documents(environment, duplicate_key);

CREATE TABLE document_fields (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  field_name TEXT NOT NULL,
  required INTEGER NOT NULL CHECK(required IN (0,1)),
  raw_source_text TEXT,
  predicted_value_json TEXT,
  final_value_json TEXT,
  confidence TEXT,
  evidence_json TEXT NOT NULL,
  source_prediction_ref TEXT NOT NULL,
  review_status TEXT NOT NULL,
  field_revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(document_id, field_name)
);

CREATE TABLE document_lines (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  sequence INTEGER NOT NULL CHECK(sequence > 0),
  source_row_ref TEXT NOT NULL,
  raw_ocr_text TEXT NOT NULL,
  supplier_sku TEXT,
  description_final TEXT,
  unit_final TEXT,
  quantity_decimal TEXT,
  free_quantity_decimal TEXT,
  unit_price_minor INTEGER,
  discount_minor INTEGER NOT NULL DEFAULT 0,
  line_total_minor INTEGER,
  ada_product_code TEXT,
  ada_product_name_snapshot TEXT,
  ada_unit_code TEXT,
  match_status TEXT NOT NULL DEFAULT 'UNRESOLVED',
  match_method TEXT,
  current_prediction_id TEXT,
  review_status TEXT NOT NULL DEFAULT 'UNREVIEWED',
  evidence_json TEXT NOT NULL,
  row_revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(document_id, sequence)
);

CREATE TABLE erp_ground_truth (
  id TEXT PRIMARY KEY,
  supplier_code TEXT NOT NULL,
  receipt_number TEXT NOT NULL,
  line_sequence INTEGER NOT NULL,
  product_code TEXT NOT NULL,
  product_name_as_entered TEXT NOT NULL,
  quantity_decimal TEXT NOT NULL,
  unit_code TEXT NOT NULL,
  price_minor INTEGER NOT NULL,
  source_kind TEXT NOT NULL CHECK(source_kind IN ('FIXTURE','EXTERNAL_APPROVED_IMPORT')),
  created_at TEXT NOT NULL,
  UNIQUE(receipt_number, line_sequence)
);

CREATE TABLE document_links (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  receipt_number TEXT NOT NULL,
  method TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  verified_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE line_links (
  id TEXT PRIMARY KEY,
  document_line_id TEXT NOT NULL REFERENCES document_lines(id),
  erp_ground_truth_id TEXT NOT NULL REFERENCES erp_ground_truth(id),
  method TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  verified_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE supplier_product_aliases (
  id TEXT PRIMARY KEY,
  supplier_code TEXT NOT NULL,
  normalized_supplier_text TEXT NOT NULL,
  ada_product_code TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('CANDIDATE','ELIGIBLE','ACTIVE','QUARANTINED','DISABLED')),
  confirmation_count INTEGER NOT NULL DEFAULT 0,
  correction_count INTEGER NOT NULL DEFAULT 0,
  distinct_document_count INTEGER NOT NULL DEFAULT 0,
  observed_document_ids_json TEXT NOT NULL,
  approved_by TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(supplier_code, normalized_supplier_text, ada_product_code)
);

CREATE TABLE layer_f_predictions (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  document_line_id TEXT NOT NULL REFERENCES document_lines(id),
  tier TEXT NOT NULL,
  method TEXT NOT NULL,
  source_text TEXT NOT NULL,
  normalized_text TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  proposed_product_code TEXT,
  proposed_unit_code TEXT,
  confidence TEXT,
  candidate_set_json TEXT NOT NULL,
  reason_codes_json TEXT NOT NULL,
  provenance_json TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  ocr_engine_versions_json TEXT NOT NULL,
  ruleset_version TEXT NOT NULL,
  model_version TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE review_events (
  id TEXT PRIMARY KEY,
  interaction_id TEXT NOT NULL,
  target_type TEXT NOT NULL CHECK(target_type IN ('HEADER','PRODUCT','LINE_VALUE')),
  document_id TEXT NOT NULL REFERENCES documents(id),
  document_field_id TEXT REFERENCES document_fields(id),
  document_line_id TEXT REFERENCES document_lines(id),
  field_name TEXT,
  prediction_id TEXT REFERENCES layer_f_predictions(id),
  source_prediction_ref TEXT,
  action TEXT NOT NULL CHECK(action IN ('CONFIRM','CORRECT','REJECT','MARK_NEEDS_REVIEW','RETRACT_LABEL')),
  original_value_json TEXT NOT NULL,
  proposed_value_json TEXT NOT NULL,
  final_value_json TEXT NOT NULL,
  error_category TEXT,
  evidence_json TEXT NOT NULL,
  versions_json TEXT NOT NULL,
  reviewer_id TEXT NOT NULL,
  reviewer_display_name TEXT NOT NULL,
  decision_duration_ms INTEGER NOT NULL CHECK(decision_duration_ms >= 0),
  occurred_at TEXT NOT NULL,
  supersedes_event_id TEXT REFERENCES review_events(id),
  CHECK(action NOT IN ('CORRECT','REJECT','RETRACT_LABEL') OR error_category IS NOT NULL),
  CHECK(
    (target_type='HEADER' AND document_field_id IS NOT NULL AND prediction_id IS NULL AND source_prediction_ref IS NOT NULL)
    OR (target_type='PRODUCT' AND document_line_id IS NOT NULL AND prediction_id IS NOT NULL)
    OR (target_type='LINE_VALUE' AND document_line_id IS NOT NULL AND source_prediction_ref IS NOT NULL)
  )
);

CREATE TABLE automation_runs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  document_revision INTEGER NOT NULL,
  review_snapshot_hash TEXT NOT NULL,
  driver_kind TEXT NOT NULL CHECK(driver_kind IN ('FAKE','REPLAY','LIVE_DISABLED')),
  idempotency_key TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL,
  current_step TEXT NOT NULL,
  current_line_sequence INTEGER,
  target_company TEXT NOT NULL,
  target_branch TEXT NOT NULL,
  preflight_json TEXT NOT NULL,
  preflight_hash TEXT NOT NULL,
  reconciliation_json TEXT,
  reconciliation_hash TEXT,
  started_by TEXT NOT NULL,
  save_authorized_by TEXT,
  save_token_hash TEXT,
  save_token_expires_at TEXT,
  save_token_consumed_at TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  ada_document_number TEXT,
  failure_code TEXT,
  receipt_artifact_ref TEXT
);

CREATE TABLE automation_events (
  id TEXT PRIMARY KEY,
  automation_run_id TEXT NOT NULL REFERENCES automation_runs(id),
  sequence INTEGER NOT NULL,
  message_id TEXT NOT NULL,
  command_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  step TEXT NOT NULL,
  line_sequence INTEGER,
  expected_json TEXT NOT NULL,
  observed_json TEXT NOT NULL,
  evidence_ref TEXT,
  occurred_at TEXT NOT NULL,
  UNIQUE(automation_run_id, sequence),
  UNIQUE(automation_run_id, message_id)
);

CREATE TABLE audit_events (
  id TEXT PRIMARY KEY,
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  before_hash TEXT,
  after_hash TEXT,
  detail_json TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);

CREATE TRIGGER layer_f_predictions_no_update BEFORE UPDATE ON layer_f_predictions BEGIN SELECT RAISE(ABORT, 'append-only layer_f_predictions'); END;
CREATE TRIGGER layer_f_predictions_no_delete BEFORE DELETE ON layer_f_predictions BEGIN SELECT RAISE(ABORT, 'append-only layer_f_predictions'); END;
CREATE TRIGGER review_events_no_update BEFORE UPDATE ON review_events BEGIN SELECT RAISE(ABORT, 'append-only review_events'); END;
CREATE TRIGGER review_events_no_delete BEFORE DELETE ON review_events BEGIN SELECT RAISE(ABORT, 'append-only review_events'); END;
CREATE TRIGGER automation_events_no_update BEFORE UPDATE ON automation_events BEGIN SELECT RAISE(ABORT, 'append-only automation_events'); END;
CREATE TRIGGER automation_events_no_delete BEFORE DELETE ON automation_events BEGIN SELECT RAISE(ABORT, 'append-only automation_events'); END;
CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'append-only audit_events'); END;
CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'append-only audit_events'); END;

INSERT INTO schema_migrations(version, applied_at) VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
