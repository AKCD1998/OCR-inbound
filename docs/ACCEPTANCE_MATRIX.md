# Staging MVP Acceptance Matrix

Last updated: 2026-07-22

| Requirement | Evidence | Status |
|---|---|---|
| Documented app/package launches | `run_staging.ps1`; packaged server health probe in `scripts/package_smoke.py` | PASS |
| Inbox PDF/image + reviewed artifact import | `/api/import`, immutable store, UI file inputs, loopback integration test | PASS |
| Existing Layers A–E reused | `ExistingOcrPipelineAdapter`, supervised OCR worker, Layer E review-gated importer; legacy pipeline unchanged | PASS (adapter/contract) |
| Top 3 import → review → match → correct → Ready | Woothi, Charoon Bhesaj, Berlin Pharma fixtures in `TopThreeEndToEndTests` | PASS |
| Immutable source + SHA-256 duplicate open-existing | artifact/repository integration test and duplicate audit event | PASS |
| Prediction committed before display | transaction visibility and forced repository-failure tests | PASS |
| Product decision references prediction; header references source | DB constraints plus product/header review tests | PASS |
| Append-only labeled decisions and audit | SQLite reject-update/delete triggers, repository readers, integration tests | PASS |
| Monotonic interaction timing and deduplicated bulk timing | browser `performance.now`; shared interaction ID; metric aggregation test | PASS |
| Decimal/scaled-integer exact validators | money, Thai numeral/date, line and grand-total tests | PASS |
| Master-only deterministic Layer F | tier cascade, persisted provenance, out-of-master and alias tests | PASS |
| Alias 3-distinct-document gate/approval/quarantine | alias writer/reader integration test | PASS |
| File/business/pre-save duplicate gates | repository, validation, and Fake driver fault tests | PASS |
| Revision invalidates snapshot/token | review revision and save authorization tests | PASS |
| Exact row count/grand total; UNKNOWN fails | reconciliation fault suite | PASS |
| Fake/Replay human-gated simulated save | full end-to-end driver tests and completion receipts | PASS |
| Popup/focus/input/lookup/timeout/crash/mismatch stop safely | required failure injection tests | PASS |
| Startup recovery | orphaned OCR fails closed; orphaned automation pauses/clears token | PASS |
| Environment isolation/redaction | config/path/log tests and System Health | PASS |
| Backup/restore/integrity | restore drill integration test | PASS |
| Reproducible staging package | stdlib-only runtime lock, zipapp SHA-256 manifest, self-check and launch health smoke | PASS |
| Live unproven capability disabled | config/health test and `docs/EXTERNAL_BLOCKERS.md` | PASS |
| Thai keyboard/DPI contract | static UI contract tests; 100/125/150% CSS rules | PASS (contract) |
| Actual Chrome DPI screenshot | delayed 125% artifact manually inspected; capture command failed and 100/150% visuals absent | PARTIAL / non-terminal tool limitation |

The 30-document live ADA ≥95% criterion, read-only AdaAcc permission proof, and production activation
are not local staging terminal conditions. They remain explicitly unpassed.
