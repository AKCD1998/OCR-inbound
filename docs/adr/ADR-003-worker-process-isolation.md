# ADR-003 — Worker process isolation

Decision: OCR and ADA automation use versioned JSONL stdin/stdout workers; diagnostics use stderr.
Context: OCR/Win32 can hang or crash and workers must not write `app.db`. Consequence: explicit
heartbeat, cancellation, replay, and protocol tests. Revisit only if the measured process overhead
prevents the north-star workflow.
