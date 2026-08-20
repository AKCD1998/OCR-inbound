# ADR-007 — Human-gated one-use save

Decision: draft fill and save are separate commands. Save requires a short-lived one-use token bound
to run, document revision, preflight, reconciliation, actor, and expiry. Any edit or mismatch
invalidates it. Consequence: no auto-save; fake/replay simulated save can be tested safely. Live Save
remains blocked by this goal's production boundary.
