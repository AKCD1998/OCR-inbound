# ADR-006 — Persist prediction before display

Decision: every deterministic Layer F tier, including unresolved, is inserted into
`layer_f_predictions` and committed before a review DTO is queried. Product decisions require that
prediction ID. Consequence: UI never displays an untraceable match and repository failure becomes a
retry state. Revisit only through a Project Bible amendment.
