# Schema Writer / Reader / Test Map

Migration: `src/ocr_inbound/migrations/0001_initial.sql` (`schema_version=1`). SQLite is staging-only,
single-host, WAL-enabled, foreign-key enforced, and backed up before migration of an existing file.

| Table | Writer(s) | Reader(s) | Main test coverage |
|---|---|---|---|
| `documents` | create/import/status/Ready/recovery commands | get/list/hash/duplicate | Foundation, Validation, Reliability, TopThree |
| `document_fields` | OCR projection, atomic header review | `list_fields` / workspace | LearningPlane, TopThree, UI |
| `document_lines` | OCR projection, atomic line/product review | `list_lines` / workspace | LearningPlane, Validation, TopThree |
| `automation_runs` | orchestrator lifecycle and token commands | get/list/System Health | AutomationHappyPath, AutomationFault, Reliability |
| `automation_events` | append-only orchestrator event writer | get/list/receipt chain | AutomationHappyPath/Fault |
| `audit_events` | transaction-local and public audit appenders | `list_audit_events`, metrics | Foundation, LearningPlane, Automation |
| `erp_ground_truth` | approved fixture-import contract writer | `list_erp_ground_truth` | LearningPlane fixture writer/reader |
| `document_links` | verified alignment-link writer | `list_document_links` | LearningPlane fixture writer/reader |
| `line_links` | verified line-link writer | `list_line_links` | LearningPlane fixture writer/reader |
| `supplier_product_aliases` | observation/eligibility/approval/quarantine commands | get/list/matcher | LearningPlane alias gate/conflict |
| `layer_f_predictions` | prediction-before-display transaction | get/list/workspace | LearningPlane forced-failure/append-only |
| `review_events` | atomic header/product/value/bulk decisions | get/list/metrics | LearningPlane and TopThree |

Prediction, review, automation-event, and audit history tables have database triggers rejecting
UPDATE and DELETE. Current projections remain mutable only in the same transaction that appends the
corresponding decision/audit evidence.
