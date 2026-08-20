# OCR Inbound Staging MVP — Implementation Plan

Date: 2026-07-22
Goal: `019f8845-c096-7621-85f7-803fcbfbfebc`

## Guardrails

- Preserve existing Layers A–E and the legacy fusion review server/UI; integrate through a
  versioned artifact adapter.
- Build a staging-only operational companion around the 5 conceptual schema groups / 6 physical
  learning-plane tables. Do not claim the first-five milestone or a stage advance.
- Use Decimal/scaled integers for quantities and money. Predictions, review events, automation
  events, and audit events are append-only.
- Keep live ADA and live AdaAcc disabled until external proof exists. Never write AdaAcc directly
  and never Save/Approve in ADA production.

## Vertical slices

1. **Governance and evidence** — worktree inventory, Bible amendment, ledger decision record,
   acceptance matrix, status/evidence/blocker documents.
2. **Comparative UI spike** — the same 120-row Thai fixture and evidence image across PySide6,
   local-web reuse, and .NET/WPF; record measurable toolchain/runtime/keyboard/packaging results;
   select the lowest-complexity passing stack in an ADR.
3. **Foundation and Inbox** — environment isolation, explicit staging identity, SQLite WAL,
   immutable artifact store, hash/open-existing duplicate behavior, migration/backup/integrity,
   structured redacted logs.
4. **OCR and review** — supervised existing-pipeline command adapter, versioned artifact importer,
   Top 3 golden fixtures, header/line projections, evidence refs, keyboard-first review commands,
   atomic correction + append-only label/audit events, revision invalidation.
5. **Layer F and Ready** — isolated ADA reference cache, deterministic master-only matching,
   prediction-before-display, alias eligibility/quarantine, exact validation and duplicate gates,
   canonical review snapshot.
6. **ADA Fake/Replay** — versioned JSONL protocol, deterministic drivers, mutex, checkpoints,
   exact readback, one-use human save token, simulated save, completion receipt, metrics, and all
   required safe-stop fault injections. Live driver remains disabled.
7. **UI, packaging, and handoff** — launchable Thai-first staging UI, system health, backup/restore,
   reproducible staging package, end-to-end Top 3 run, automated QA, README/runbook/status/blockers.

Each slice is complete only when it has a writer, reader, and automated test/evidence. Exact commands
and results are recorded in `docs/IMPLEMENTATION_STATUS.md`.
