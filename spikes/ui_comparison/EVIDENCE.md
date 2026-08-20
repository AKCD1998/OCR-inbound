# Comparative UI Spike Evidence

Date: 2026-07-22
Fixture: `ui-spike.v1`, 120 Thai line items, shared `evidence_invoice.svg`

Command:

```powershell
.\.venv\Scripts\python.exe .\spikes\ui_comparison\evaluate.py
```

## Results

| Criterion | PySide6 / Qt Widgets | Local-web desktop | .NET / WPF |
|---|---|---|---|
| Toolchain | `ModuleNotFoundError`, exit 3, 69.62 ms | Python 3.11 stdlib + installed browser; runnable | `dotnet` missing, exit 127, 4.94 ms |
| 120-row table | QTableView spike source present; not executed | Bounded DOM virtualization; only visible rows rendered | Virtualized DataGrid source present; not compiled |
| Thai | Source contains the same Thai fixture | Leelawadee UI/Tahoma stack and Thai fixture | Same Thai fixture in source |
| Keyboard/focus | Model spike only; dependency blocks interaction proof | Arrow, Enter, Ctrl+Enter, F8; grid retains focus | Source-only; SDK blocks interaction proof |
| Evidence | Shared SVG planned in UI | Adjacent shared SVG rendered by the page | Shared SVG referenced by XAML |
| DPI | Cannot run | CSS rules for 100/125/150%; a 125% capture artifact was manually inspected, but capture reliability and 100/150% visuals remain unpassed | Cannot run |
| Worker boundary | Python-compatible | HTTP/API boundary naturally keeps OCR/Win32 outside UI code | Python sidecar required |
| Existing UI reuse | Low | High: reuses local HTTP/static patterns and visual language from `fusion_review_ui` | Low |
| Added runtime dependencies | PySide6 + packaging stack | None beyond Python/browser already present | .NET Desktop Runtime/SDK + sidecar |

Chrome headless visual capture was attempted twice and timed out/returned exit 1. A 1996×1248 PNG
subsequently materialized and was manually inspected: Thai text, adjacent evidence, the 120-row count,
bounded 37-row DOM, and active-row focus are visible for the requested 125% run. Because the capture
command itself was unreliable and no 100/150% visual artifacts exist, this is partial evidence rather
than a full DPI visual pass. The generated PNG is ignored; the checked-in SVG remains the synthetic
shared fixture.

## Decision

Select **local-web desktop** for the staging MVP. It is the only option runnable in the current
toolchain, handles the shared 120-row workload with bounded DOM virtualization, reuses the legacy
diagnostic UI patterns, keeps the Win32/OCR worker boundary unchanged, and adds no ecosystem-sized
dependency. Revisit native Qt only if measured browser keyboard/focus/accessibility problems appear
during user testing. WPF requires a separately approved .NET toolchain and Python sidecar.
