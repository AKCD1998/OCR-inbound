# ADR-008 — Staging and production isolation

Decision: environments have separate DB, cache, artifact root, credential key, mutex, badge, and
target allowlist. Production live automation/save flags default false and cannot be enabled by the
staging profile. Consequence: more explicit configuration, but no accidental cross-environment path.
Revisit only with production activation authorization.
