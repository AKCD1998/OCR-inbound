# ADR-001 — Local modular monolith

Decision: use one local application host as the sole operational DB writer, with OCR and ADA work in
supervised processes. Context: one workstation per ADA instance. Alternatives: distributed services
or a shared server add unsupported coordination. Consequence: simple local transactions; a shared
queue requires a new review. Revisit when multi-workstation scope is authorized.
