# OCR Inbound Staging Runbook

Last updated: 2026-08-21

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

## Product-master cache refresh (Slice 5, read-only)

The matcher never queries production. It reads a LOCAL `ada_cache.db` only. This section is the one
operator procedure that repopulates that local cache from the read-only production snapshot.

**Boundary.** The refresh opens a session that is forced read-only before anything else runs, checks
`SHOW transaction_read_only = on`, confirms `current_database() = sc_drug_db`, runs exactly one
`SELECT` from `ada.branch_stock_snapshots`, and always `ROLLBACK`s. Every statement it may send is in
the `QUERY_ALLOWLIST` catalog in `src/ocr_inbound/master_cache.py`; there is no `INSERT`, `UPDATE`,
`DELETE`, or DDL on this path, and none can be added without failing `assert_allowlist_safe()`.
This command does not touch ADA, AdaAcc, Save/Approve, or any feature flag.

### Operator setup

The connection string is supplied by the operator at run time through the `OCR_MASTER_DATABASE_URL`
environment variable. **Never** write it into a file in this repository, a script, a scheduled task
definition, or a ticket. Set it for the current shell only, so it disappears when the shell closes:

```powershell
# Prompts without echoing; the value is never written to disk or to the console.
$secure = Read-Host -AsSecureString "OCR_MASTER_DATABASE_URL"
$env:OCR_MASTER_DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
```

Use a database role that holds `SELECT` on `ada.branch_stock_snapshots` and nothing more. If the DSN
contains `@`, `/`, `#`, `?`, or `:` inside the username or password, those characters must be
percent-encoded in the URL (`p@ss` becomes `p%40ss`); the refresh decodes them before connecting.

Clear it when you are done:

```powershell
Remove-Item Env:\OCR_MASTER_DATABASE_URL
```

### Dependency installation

The staging app, the review UI, the matcher, the packaged zipapp, and the whole test suite are
standard-library only. The refresh is the single path that needs a PostgreSQL driver, imported lazily
so nothing else is affected:

```powershell
.\.venv\Scripts\python.exe -m pip install "pg8000>=1.31,<2.0"
```

It is declared in `requirements.txt` and as the `master-refresh` extra in `pyproject.toml`. On a
machine without it, the refresh — and only the refresh — fails loudly with
`MASTER_REFRESH_DRIVER_MISSING`; import, review, Ready, Fake/Replay, and the packaged build all keep
working.

### Refresh and status commands

```powershell
$env:PYTHONPATH = ".\src"
.\.venv\Scripts\python.exe -m ocr_inbound master-cache-refresh
.\.venv\Scripts\python.exe -m ocr_inbound master-cache-status
```

Both are staging-only (`MASTER_REFRESH_STAGING_ONLY` otherwise) and both print JSON containing counts,
`refreshed_at`, `source_fingerprint`, `stale`, and `integrity`. Neither prints the host, the user, the
password, or any part of the DSN, and no credential is written to `logs/` or into `ada_cache.db`.

### Expected count band

The refresh refuses any snapshot outside **5,000–10,000** products (`MASTER_COUNT_OUT_OF_BAND`), which
is a guard against a truncated or wrong-instance read, not a target. The verified live count on
2026-08-21 was **6,671** products (6,671 distinct `product_code` values, 6,670 with a unit). A result
that is inside the band but far from ~6,671 still deserves investigation before the cache is trusted.

### What `active = 1` means in this cache

`ada.branch_stock_snapshots` has **no `is_active` column**. The cache's `products.active = 1`
therefore means exactly, and only:

> present in the current branch-stock snapshot and eligible for staging review matching

It is **not** a production claim that the product is commercially active, stocked, orderable, or
current, and a product's absence from a later snapshot is **not** evidence that it was retired. No
retirement state exists in the source and none is inferred. Do not report cache `active` counts as
"active products" to anyone.

### Failure behaviour — no fallback

Every failure is loud and leaves the previous `ada_cache.db` **byte-identical**. There is no silent
fallback to the packaged fixture, no partial write, and no "best effort" cache:

- `MASTER_DATABASE_URL_MISSING` — `OCR_MASTER_DATABASE_URL` is not set.
- `MASTER_REFRESH_DRIVER_MISSING` — install `pg8000` as above.
- `MASTER_CONNECT_FAILED` — could not open the session; check the variable, network, and credentials.
  The message is deliberately credential-free, so diagnose from the DSN you hold, not from the error.
- `MASTER_NOT_READ_ONLY` / `MASTER_WRONG_DATABASE` — a guard refused the session before any product
  row was read. Do not work around these.
- `MASTER_COUNT_OUT_OF_BAND`, `MASTER_CANDIDATE_INVALID`, `MASTER_PRODUCT_CONFLICT`,
  `MASTER_NAME_MISSING`, `MASTER_INVALID_PRODUCT_CODE` — the snapshot failed the data contract; the
  old cache is still in place and still the one the matcher uses.

A refresh builds a temporary `*.next` candidate beside the cache and only ever `os.replace`s it in
after full validation. A failed refresh cleans up its own candidate; seeing a leftover `*.next` file
is itself a bug worth reporting. Confirm the previous cache is untouched with:

```powershell
Get-FileHash .\environments\staging\ocr_inbound_app\ada_cache.db -Algorithm SHA256
Get-ChildItem .\environments\staging\ocr_inbound_app\*.next   # expect: no matches
```

### Startup never refreshes

`Application.bootstrap` does not call the refresh, and `master_cache` is not imported at application
start — `__main__.py` imports it inside the two `master-cache-*` command branches only. Launching the
server, importing an invoice, or opening the UI can never reach production. Verify on any machine:

```powershell
$env:PYTHONPATH = ".\src"
.\.venv\Scripts\python.exe -c @"
import sys, tempfile
from pathlib import Path
from ocr_inbound.service import Application
Application.bootstrap(environment='staging', data_root=Path(tempfile.mkdtemp()), reviewer_id='probe.reviewer')
assert 'ocr_inbound.master_cache' not in sys.modules, 'refresh module was imported at startup'
assert 'pg8000' not in sys.modules, 'database driver was imported at startup'
print('PASS: startup never auto-refreshes')
"@
```

Verified 2026-08-21: neither `ocr_inbound.master_cache` nor `pg8000` appears in `sys.modules` after
importing the app or after `Application.bootstrap`.

A refresh happens only when a human types `master-cache-refresh`.

### Stale refresh lock

A refresh holds `master_cache_refresh.lock` in the environment root and removes it on both success and
failure. If a process is killed (Ctrl+C mid-write, terminal closed, host reboot, task manager), the
lock file can survive with no process behind it. The next refresh then stops with
`MASTER_REFRESH_IN_PROGRESS` and reports the recorded holder, for example
`pid=12345 started_at=2026-08-21T07:59:09+00:00`.

**Never delete the lock reflexively.** A live refresh and a stranded lock look identical from the file
alone, and deleting a live one allows two refreshes to replace the same cache concurrently. Diagnose
first:

1. Read the holder: `Get-Content .\environments\staging\ocr_inbound_app\master_cache_refresh.lock`
2. Check whether that PID still exists **and is actually a Python refresh**, not a reused PID:
   ```powershell
   Get-CimInstance Win32_Process -Filter "ProcessId=12345" |
     Select-Object ProcessId, Name, CreationDate, CommandLine
   ```
3. If a process exists whose command line contains `master-cache-refresh`, it is **live** — wait for
   it. Do not delete the lock and do not kill it mid-replace.
4. If no such process exists, or the PID belongs to an unrelated program, the lock is stale. Confirm
   nothing is mid-write — `master-cache-status` still reports the old cache and no `*.next` file
   remains — then remove it deliberately:
   ```powershell
   Get-ChildItem .\environments\staging\ocr_inbound_app\*.next    # expect: no matches
   Remove-Item .\environments\staging\ocr_inbound_app\master_cache_refresh.lock
   ```
5. Re-run `master-cache-status` before re-running the refresh. Because the previous cache is only ever
   replaced atomically after validation, a killed refresh cannot have left a half-written cache — the
   worst case is the orphan lock and, if the kill was hard enough to skip cleanup, a stray `*.next`
   file that is safe to delete once no refresh is running.

## Failure handling

- `READY_VALIDATION_FAILED`: resolve reported expected/observed issue; `UNKNOWN` is blocking.
- `STALE_DOCUMENT_REVISION`: discard the old authorization/run and validate the current revision.
- `SAVE_TOKEN_USED` / `SAVE_TOKEN_EXPIRED`: reconcile again and request a new human authorization.
- `ADA_*`, `HOST_RESTARTED`, or `SAFE_PAUSE`: input is stopped and no Save is guessed; inspect events.
- `LIVE_ADA_DISABLED`, `LIVE_ADACC_DISABLED`, or `PRODUCTION_ACTIVATION_BLOCKED`: expected guardrail,
  not an instruction to bypass the feature flag.

See `docs/EXTERNAL_BLOCKERS.md` before any separately authorized live staging work.
