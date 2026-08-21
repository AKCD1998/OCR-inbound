-- Slice 2 (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 22): supplier-agnostic
-- "approved spelling/name alias" table, for the new SPELLING_ALIAS tier.
--
-- This is deliberately a SEPARATE table from `supplier_product_aliases`
-- (added in 0001), not a generalization of it. supplier_product_aliases is
-- scoped to (supplier_code, text) because a given supplier's shorthand only
-- means one particular thing on THAT supplier's invoices. A spelling/name
-- alias is different in kind: it records that a piece of text (a common
-- Thai transliteration, an abbreviation, a recurring OCR misread) reliably
-- refers to one catalog product REGARDLESS of which supplier's invoice it
-- appears on -- e.g. "มินิเดียบ" meaning MINIDIAB is true for every
-- supplier, not a Woothi-specific shorthand. Mixing the two scopes into one
-- table would either force spelling aliases to be re-approved per supplier
-- (wrong -- wastes review effort on something supplier-independent) or let
-- a supplier-specific shorthand leak into every other supplier's invoices
-- (wrong -- exactly the kind of over-broad match Layer F has repeatedly had
-- to guard against). Same CANDIDATE -> ELIGIBLE -> ACTIVE lifecycle and
-- confirmation-count promotion rule as supplier_product_aliases, for
-- consistency and because it is already a tested, understood pattern -- see
-- Repository.record_name_alias_observation / approve_name_alias.
CREATE TABLE product_name_aliases (
  id TEXT PRIMARY KEY,
  normalized_text TEXT NOT NULL,
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
  UNIQUE(normalized_text, ada_product_code)
);

INSERT INTO schema_migrations(version, applied_at) VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
