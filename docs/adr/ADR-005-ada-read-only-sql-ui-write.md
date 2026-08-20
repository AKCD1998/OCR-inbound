# ADR-005 — Read-only AdaAcc and ADA UI draft entry

Decision: AdaAcc adapters expose named parameterized SELECT methods only; ADA draft entry uses a
driver through the application orchestrator. Direct database mutation is forbidden. Live adapters
remain disabled until schema, permission, and staging target proofs exist. Consequence: fake/cache and
Replay/Fake drivers provide local completeness. Revisit only under a separately authorized live goal.
