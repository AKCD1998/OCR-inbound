CREATE TABLE product_review_decisions (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL UNIQUE,
  request_fingerprint TEXT NOT NULL,
  document_id TEXT NOT NULL REFERENCES documents(id),
  document_line_id TEXT NOT NULL REFERENCES document_lines(id),
  prediction_id TEXT NOT NULL REFERENCES layer_f_predictions(id),
  action TEXT NOT NULL CHECK(action IN ('CONFIRM','CORRECT','UNREADABLE','NOT_IN_MASTER','DEFER')),
  selected_product_code TEXT,
  selected_unit_code TEXT,
  supplier_code TEXT NOT NULL,
  normalized_alias TEXT,
  ruleset_version TEXT NOT NULL,
  corrected_ocr_text TEXT,
  error_category TEXT,
  reason TEXT,
  raw_ocr_sha256 TEXT NOT NULL,
  evidence_sha256 TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  duration_ms INTEGER NOT NULL CHECK(duration_ms >= 0),
  created_at TEXT NOT NULL
);
CREATE INDEX idx_product_review_queue ON product_review_decisions(document_id,document_line_id,created_at);
CREATE TRIGGER product_review_decisions_no_update BEFORE UPDATE ON product_review_decisions BEGIN SELECT RAISE(ABORT, 'append-only product_review_decisions'); END;
CREATE TRIGGER product_review_decisions_no_delete BEFORE DELETE ON product_review_decisions BEGIN SELECT RAISE(ABORT, 'append-only product_review_decisions'); END;
INSERT INTO schema_migrations(version, applied_at) VALUES (3, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
