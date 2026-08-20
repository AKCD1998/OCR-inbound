# OCR Feasibility Pipeline

Raw-output-first OCR feasibility pipeline for Thai/English pharmacy and supplier invoice PDFs.

The pipeline is designed to discover maximum extractable information, not to clean, correct, infer, or normalize OCR output.

## OCR Inbound staging application

The repository also contains a Windows, loopback-only staging companion for importing a source
PDF/image plus a reviewed `ocr-inbound-artifact.v1`, reviewing header and product lines, persisting
Layer F predictions and labeled decisions, exact validation, and Fake/Replay ADA simulation. It is
staging-only: live ADA, live AdaAcc, and production Save/Approve are disabled.

Prerequisite: the repository `.venv` must use Python 3.11. The companion itself and its packaged
runtime use only the Python standard library; existing OCR Layers A–E keep their separate legacy
dependencies in `requirements.txt`.

Launch from source with a named staging reviewer:

```powershell
.\run_staging.ps1 -Reviewer "firstname.lastname"
```

The browser opens `http://127.0.0.1:8876`. In Inbox, select the original PDF/image and its reviewed
versioned OCR artifact. The source is content-sniffed, checksummed, and stored immutably; predictions
are committed before the workspace returns them. A non-browser import is also available:

```powershell
$env:PYTHONPATH = ".\src"
.\.venv\Scripts\python.exe -m ocr_inbound --reviewer "firstname.lastname" import `
  --source .\invoice.pdf --artifact .\invoice.ocr-inbound-artifact.v1.json
```

Build and smoke-test the self-contained staging zipapp:

```powershell
.\.venv\Scripts\python.exe .\scripts\build_staging.py
.\.venv\Scripts\python.exe .\scripts\package_smoke.py
.\.venv\Scripts\python.exe .\dist\ocr-inbound-staging.pyz --reviewer "firstname.lastname" serve
```

Run all automated checks:

```powershell
$env:PYTHONPATH = ".\src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

Operational procedures, recovery behavior, data locations, and safety boundaries are in
[`docs/STAGING_RUNBOOK.md`](docs/STAGING_RUNBOOK.md). Implementation evidence and limitations are in
[`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) and
[`docs/EXTERNAL_BLOCKERS.md`](docs/EXTERNAL_BLOCKERS.md).

## Install

Use Python 3.10 or 3.11. Python 3.7 will not work with the modern OCR/PDF packages used here.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `python --version` shows `Python 3.7.x`, install Python 3.10 or 3.11 first, then recreate `.venv`.

External open-source tools should also be available on `PATH` for full coverage:

- Tesseract OCR with `tha` and `eng` language data
- Poppler, recommended for PDF utilities
- Ghostscript, recommended for Camelot scanned/table workflows
- Java, only if adding Tabula later

## Run

Place PDFs in this folder, then run:

```powershell
python .\ocr_feasibility.py .\input.pdf --out .\ocr_runs
```

Run every PDF in a directory:

```powershell
python .\ocr_feasibility.py . --out .\ocr_runs
```

Enable OpenAI as an optional second reader after OSS OCR has completed:

```powershell
$env:OPENAI_API_KEY="..."
python .\ocr_feasibility.py .\input.pdf --out .\ocr_runs --openai
```

## Environment Separation

The workspace now supports two isolated review environments:

- `production`
- `staging`

The defaults live in code in `ocr_environment.py`, and can be overridden from `.env` using the keys shown in `.env.review.example`.

Default roots:

- Production inbound: `.\environments\production\inbound`
- Production outputs: `.\ocr_runs_final`
- Production review run: `.\ocr_runs_final\18-25_3-681-5_a1752ee9b6`
- Production review port: `8765`
- Staging inbound: `.\environments\staging\inbound`
- Staging outputs: `.\ocr_runs_staging`
- Staging review run: `.\ocr_runs_staging\18-25_3-681-5_a1752ee9b6`
- Staging review port: `8766`

The review server and pipeline both validate their target paths against the active environment. A staging command cannot write into production roots, and a production command cannot load staging roots.

### Production Commands

Run OCR against the production inbound folder:

```powershell
.\.venv\Scripts\python.exe .\ocr_feasibility.py --env production
```

Run OCR against a specific production PDF:

```powershell
.\.venv\Scripts\python.exe .\ocr_feasibility.py .\environments\production\inbound\input.pdf --env production
```

Start the production review UI:

```powershell
.\.venv\Scripts\python.exe .\fusion_review_server.py --env production
```

### Staging Commands

Run OCR against the staging inbound folder:

```powershell
.\.venv\Scripts\python.exe .\ocr_feasibility.py --env staging
```

Run OCR against a specific staging PDF:

```powershell
.\.venv\Scripts\python.exe .\ocr_feasibility.py .\environments\staging\inbound\input.pdf --env staging
```

Start the staging review UI:

```powershell
.\.venv\Scripts\python.exe .\fusion_review_server.py --env staging
```

Run Layer B row reconstruction against the current staging review run:

```powershell
.\.venv\Scripts\python.exe .\ocr_feasibility.py --env staging --table-row-run-dir .\ocr_runs_staging\18-25_3-681-5_a1752ee9b6
```

Run the Layer C readiness gate and column-geometry proof of concept against staging:

```powershell
.\.venv\Scripts\python.exe .\ocr_feasibility.py --env staging --table-column-run-dir .\ocr_runs_staging\18-25_3-681-5_a1752ee9b6
```

Layer C first validates the Layer B row artifacts. If Layer B is missing or blocked, it writes `tables/table_column_readiness.md` and does not create column artifacts.

Record the staging Layer C column-geometry review decision:

```powershell
.\.venv\Scripts\python.exe .\ocr_feasibility.py --env staging --table-column-review-run-dir .\ocr_runs_staging\18-25_3-681-5_a1752ee9b6 --table-column-review-decision accept
```

Check whether the staging run is ready for Layer D semantic work:

```powershell
.\.venv\Scripts\python.exe .\ocr_feasibility.py --env staging --layer-d-readiness-run-dir .\ocr_runs_staging\18-25_3-681-5_a1752ee9b6
```

### Side-by-Side Review

You can run both review servers at once:

```powershell
.\.venv\Scripts\python.exe .\fusion_review_server.py --env production
.\.venv\Scripts\python.exe .\fusion_review_server.py --env staging
```

Expected URLs:

- Production: `http://127.0.0.1:8765`
- Staging: `http://127.0.0.1:8766`

## Output Contract

Each PDF gets its own output folder containing:

- `analysis.json`: PDF metadata, digital/scanned indicators, extraction challenges
- `pages/page-0001.png`: original rasterized page images
- `preprocessed/page-0001/*.png`: preprocessing variants
- `ocr/native/`: native PDF text extraction
- `ocr/tesseract/`: raw Tesseract text and TSV
- `ocr/paddle/`: raw PaddleOCR JSON/text
- `ocr/easyocr/`: raw EasyOCR JSON/text
- `ocr/openai/`: raw OpenAI responses and parsed second-reader output, only when enabled
- `tables/`: table extraction attempts
- `comparison/`: disagreement and overlap summaries
- `report.md`: feasibility report

Staging table-understanding proof-of-concept artifacts are additive:

- `tables/table_bands.json`: Layer A table-band geometry
- `tables/table_rows.json`: Layer B row groups, when the row pass has run
- `tables/table_columns.json`: Layer C column geometry, only after Layer B passes readiness
- `tables/table_column_readiness.md`: Layer C gate report when rows are missing or insufficient
- `tables/table_column_review_decisions.json`: accepted/rejected human review of Layer C geometry before Layer D
- `tables/table_cells.json`: Layer C row/column cell geometry and preserved OCR evidence

The OpenAI stage never replaces OSS OCR outputs. Disagreements are flagged instead of resolved.
