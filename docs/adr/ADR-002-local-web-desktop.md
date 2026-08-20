# ADR-002 — Local-web desktop UI

Decision: serve a Thai-first local web UI on loopback from the Python application host. Evidence:
`spikes/ui_comparison/EVIDENCE.md` uses the same 120-row fixture for PySide6, local-web, and WPF;
only local-web is runnable without adding an unavailable ecosystem and it reuses the legacy UI's
static/HTTP patterns. Consequence: browser focus/printing must be tested; UI code still calls only
application APIs. Revisit if measured keyboard, DPI, or accessibility acceptance fails.
