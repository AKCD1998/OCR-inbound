# OCR Inbound Staging MVP — Implementation Status

Last updated: 2026-07-22

## Current outcome

`STAGING MVP COMPLETE — PRODUCTION ACTIVATION BLOCKED`

This outcome is limited to local Windows staging with Fake/Replay ADA. No live ADA action, direct
AdaAcc write, production Save/Approve, first-five milestone completion, or stage advance is claimed.

## Baseline and preservation

- No `AGENTS.md` was present.
- Existing user work was preserved: the pre-existing modified `fusion_review_server.py`,
  `adapos_receiving_probe.png`, and supplied design/architecture/corroboration/prompt documents were
  not reset, deleted, or committed.
- No local first-five schema implementation/migration was found before this goal. External existence
  remains `NOT_FOUND_IN_WORKSPACE`, not disproved.
- `.venv` is Python 3.11.9. The selected app/package uses the standard library only. PySide6,
  SQLAlchemy, Alembic, pytest, and pytest-qt were absent; .NET SDK was unavailable.

## UI decision

ADR-002 selects a Thai-first local web UI bound to loopback. The shared 120-row spike ran with the
same fixture/evidence image: local-web was runnable; PySide6 exited explicitly because the package
was absent; WPF could not build because .NET SDK was absent. Chrome headless capture attempts
timed out/failed; a delayed 125% artifact was manually inspected for Thai/evidence/focus rendering,
but no reliable capture or 100/150% visual pass is claimed. Keyboard/DPI behavior is covered as a
code contract; full 100/125/150% visual inspection remains a non-terminal manual follow-up.

## Vertical slices

| Slice | Status | Delivered evidence |
|---|---|---|
| Governance | Complete | Project Bible §9.1; ledger §17; plan/evidence/blocker/acceptance docs |
| UI comparison | Complete | `spikes/ui_comparison/EVIDENCE.md`; ADR-002; local-web selected |
| Foundation/Inbox | Complete | isolated profile, identity, migration/WAL, immutable upload/hash, recovery, redacted logs |
| OCR/Review | Complete | unchanged Layers A–E command adapter, OCR worker, reviewed artifact v1 importer, UI/CLI import, atomic review events |
| Layer F/Ready | Complete | read-only cache, deterministic persisted matches, alias gate, exact validation/duplicates/revision snapshot |
| Fake/Replay ADA | Complete | JSONL worker, mutex, exact readback, human one-use token, simulated receipt, required fault suite |
| UI/package/handoff | Complete | loopback UI, health, backup/restore, zipapp manifest, launch/worker smoke, README/runbook |

## Verification log

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe --version` | PASS — Python 3.11.9 |
| `.venv\Scripts\python.exe .\spikes\ui_comparison\evaluate.py` | PASS — 120-row comparison; local-web selected; missing PySide6/.NET recorded |
| Chrome headless screenshot attempts + delayed artifact inspection | PARTIAL — command timeout/exit 1; 125% artifact inspected; 100/150% absent |
| `.venv\Scripts\python.exe -m compileall -q src tests scripts` | PASS |
| `$env:PYTHONPATH='src'; .venv\Scripts\python.exe -m unittest tests.test_core -v` | PASS — 16/16 |
| `$env:PYTHONPATH='src'; .venv\Scripts\python.exe -m unittest tests.test_automation -v` | PASS — 10/10 before worker-crash case was added |
| `$env:PYTHONPATH='src'; .venv\Scripts\python.exe -m unittest tests.test_system -v` | PASS — 10/10 |
| `$env:PYTHONPATH='src'; .venv\Scripts\python.exe -W error::ResourceWarning -m unittest tests.test_automation.WorkerProtocolTests -v` | PASS — 2/2, including real worker crash |
| `... -m unittest discover -s tests -v` | COMMAND ERROR — relative imports lacked project top-level; README corrected to `-t .` |
| `$env:PYTHONPATH='src'; .venv\Scripts\python.exe -W error::ResourceWarning -m unittest discover -s tests -t . -v` | PASS — 37/37 in 289.533 s |
| `$env:PYTHONPATH='src'; .venv\Scripts\python.exe .\scripts\safety_scan.py` | PASS — no runtime secret matches; live query catalog SELECT-only; live flags off |
| `.venv\Scripts\python.exe scripts\build_staging.py` | PASS — 156,723-byte zipapp; SHA-256 `79d070898b0cd4ca74c6b8cdb610aeada947752d641beb024189364f6fd7f044` |
| `.venv\Scripts\python.exe scripts\package_smoke.py` | PASS — self-check, packaged Fake JSONL worker, loopback launch/health |
| `git diff --check` | PASS — tracked changes contain no whitespace errors |
| `git status --short` | PASS/REVIEWED — generated `dist/`, DB/WAL/log/cache state excluded; existing user changes remain visible |

## Runtime result

The Top-3 system test runs Woothi, Charoon Bhesaj, and Berlin Pharma through import, persisted
predictions, header confirmation, quantity/product correction, exact validation, Ready, worker-hosted
Fake draft/reconciliation, named human token, simulated Save, post-save verification, receipt, audit,
and metrics. A representative Berlin run completes through worker-hosted Replay. Across the Top-3
run, 3 documents complete and 24 labeled review decisions are persisted.

All required unknown-popup, focus-loss, physical-input, product-lookup, timeout-before/after-ack,
host/worker-crash-after-row, row-count, total, unreadable-total, pre-save duplicate, and post-save
verification faults stop as `PAUSED`/`FAILED` without guessing Save.

## Schema and original five-schema status

Migration v1 creates 6 operational and 6 learning-plane tables. Every table has an implemented
writer, reader, and test as mapped in `docs/SCHEMA_WRITER_READER_MAP.md`. The five conceptual learning
groups retain the owner-authorized names/semantics, but no external/historical production schema or
alignment precision evidence was available. Therefore first-five milestone completion and stage
advance remain explicitly unpassed.

## Live facts

Proven locally: sanitized screenshot facts listed in `docs/PHASE0_EVIDENCE.md`, SELECT-only query
catalog shape, replace-only fixture cache, driver boundary, environment allowlist, and disabled flags.

Unproven and disabled: actual AdaAcc schema/least-privilege denial proof, live ADA controls/grid order,
lookup/unit/readback semantics, staging company authorization, real document-number mapping,
Save/Approve semantics, 30-document ≥95% acceptance, production identity, RPO, and retention. See
`docs/EXTERNAL_BLOCKERS.md`.
