# ADR-004 — SQLite, ADA cache, and immutable artifacts

Decision: SQLite WAL stores local operational/learning rows, a separate replaceable SQLite file stores
ADA reference cache, and checksummed files store source/OCR/evidence/receipts. Alternatives: flat files
lack transactions; a server DB exceeds MVP topology. Consequence: one writer, backup before migration,
atomic file writes, and integrity tests. Revisit for shared queue scope.
