# OCR Inbound Staging Runbook

Last updated: 2026-07-22

## Safety boundary

This build is for `staging` only. The header must show `STAGING — NOT PRODUCTION AUTH` and System
Health must report `live_ada_enabled=false`, `live_adacc_enabled=false`, and
`production_save_enabled=false`. The only allowed ADA target is `STAGING_TEST`; Fake/Replay Save is
simulated. Do not use this runbook to write AdaAcc or click Save/Approve in live ADA.

## Launch and health

```powershell
.\run_staging.ps1 -Reviewer "firstname.lastname"
```

Use a real named reviewer; anonymous, shared, and `dao1` staging identities are rejected. The server
binds only to `127.0.0.1`. Open `http://127.0.0.1:8876/api/health` to verify database/cache integrity,
identity, startup recovery, event metrics, and disabled live flags.

For the packaged build:

```powershell
.\.venv\Scripts\python.exe .\scripts\build_staging.py
.\.venv\Scripts\python.exe .\scripts\package_smoke.py
.\.venv\Scripts\python.exe .\dist\ocr-inbound-staging.pyz --reviewer "firstname.lastname" serve
```

## Prepare and import an invoice

1. Run the existing `ocr_feasibility.py` Layers A–E flow in staging. Preserve raw engine output and
   complete the existing Layer C/E human review gates; the companion does not replace those layers.
2. Produce a reviewed `ocr-inbound-artifact.v1` JSON. It must contain the four required header
   fields, immutable source/evidence references, scaled-integer money, at least one line, OCR run ID,
   and version metadata. The fixtures under `tests/fixtures/ocr_top3/` are contract examples, not
   production ground truth.
3. In Inbox, choose the original PDF/image and the reviewed JSON, then select
   `นำเข้าและสร้าง predictions`. File hash duplicates open the existing document.
4. Confirm/correct headers and product rows. Corrections require an error category. Keyboard flow:
   Up/Down moves rows, Ctrl+Enter confirms, Ctrl+Shift+Enter bulk-confirms eligible rows, F8 moves to
   the next issue, and Alt+Down exposes persisted match provenance.
5. Resolve every blocking exception and select `ตรวจและทำ Ready`. Exact line totals, grand total,
   duplicate key, master product/unit, revision, and review snapshot must agree.
6. Use Fake or Replay draft. After exact row-count/total readback, a named human authorizes a
   short-lived one-use token, then performs `Simulated save`. The resulting receipt and append-only
   event chain are stored under the document artifact directory.

CLI import is supported when browser file selection is inconvenient:

```powershell
$env:PYTHONPATH = ".\src"
.\.venv\Scripts\python.exe -m ocr_inbound --reviewer "firstname.lastname" import `
  --source .\invoice.pdf --artifact .\invoice.ocr-inbound-artifact.v1.json
```

## Data and recovery

Default staging state is physically isolated under `environments/staging/ocr_inbound_app/`:

- `app.db`: operational and learning-plane SQLite database in WAL mode
- `ada_cache.db`: replace-only ADA reference fixture/cache; application reads it read-only
- `artifacts/`: immutable sources, manifests, checksums, and completion receipts
- `logs/`: allowlisted/redacted NDJSON application logs
- `backups/`: SQLite online backups

On startup, an orphaned OCR `PROCESSING` document fails closed. An orphaned automation run is paused
with `HOST_RESTARTED`, its save token is cleared, and blind resume is forbidden. Inspect the source,
current ADA form, and events before restarting a new Fake/Replay run.

Create a backup and verify integrity:

```powershell
$env:PYTHONPATH = ".\src"
.\.venv\Scripts\python.exe -m ocr_inbound backup
.\.venv\Scripts\python.exe -m ocr_inbound health
```

Restore only a backup located inside the selected staging root:

```powershell
.\.venv\Scripts\python.exe -m ocr_inbound restore `
  .\environments\staging\ocr_inbound_app\backups\app-YYYYMMDDTHHMMSSZ-manual.db
```

Stop the local server with Ctrl+C. RPO, backup frequency, and retention remain owner/IT decisions
and are production activation blockers.

## Failure handling

- `READY_VALIDATION_FAILED`: resolve reported expected/observed issue; `UNKNOWN` is blocking.
- `STALE_DOCUMENT_REVISION`: discard the old authorization/run and validate the current revision.
- `SAVE_TOKEN_USED` / `SAVE_TOKEN_EXPIRED`: reconcile again and request a new human authorization.
- `ADA_*`, `HOST_RESTARTED`, or `SAFE_PAUSE`: input is stopped and no Save is guessed; inspect events.
- `LIVE_ADA_DISABLED`, `LIVE_ADACC_DISABLED`, or `PRODUCTION_ACTIVATION_BLOCKED`: expected guardrail,
  not an instruction to bypass the feature flag.

See `docs/EXTERNAL_BLOCKERS.md` before any separately authorized live staging work.
