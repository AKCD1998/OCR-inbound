# ADR-009 — Reviewer identity boundary

Decision: application commands depend on an `IdentityProvider`. Staging accepts an explicit unique
named reviewer and labels it as not production authentication. Production activation requires an
owner/IT choice of Windows identity or app authentication; ADA text such as `dao1` is not treated as
proof of a human identity. Consequence: staging events remain attributable without overclaiming auth.
