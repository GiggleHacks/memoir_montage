# Changelog

All notable changes to memoir_montage. Bump the version in `pyproject.toml` and
`compilation_maker/__init__.py` for every user-facing change.

## 0.12.2 — 2026-05-18
- Fix Windows `OSError: [WinError 206] The filename or extension is too long`
  on big grids (especially the ramp peak at 8×8+). The filtergraph is now
  written to a temp file and passed via `-filter_complex_script` whenever it
  would push the command line past ~6kB, so we stay well under Windows's
  32k CreateProcess limit. The temp file is removed after the segment renders.

## 0.12.1 — 2026-05-18
- Filter checkboxes are always visible and reflect the active preset
  (Strict/Normal/Off update them live). Toggling any checkbox flips the
  preset to Custom and persists the selection.
- Filter panel re-laid out as an even two-column grid for alignment.
- Min duration is now a slider (0–30s, 0.5s steps) with a live readout
  instead of a number input.

## 0.12.0 — 2026-05-18
- Custom filter preset with per-toggle controls (e.g. Camera Only without Talking).
- Full index statistics: total runtime, indexed/failed counts, per-filter breakdown.
- Real progress for folder enumeration (streamed Found-N / current-dir updates with a
  pulsing indeterminate bar) plus a visible phase label across index and compile.
- Slider guardrails: Total Length capped to available pool seconds; Swap Interval
  capped to longest eligible clip.
- Chronological compilation order: cells within a segment and segments across the
  output flow from oldest to newest by file mtime. New "Order" toggle keeps Random
  and No-repeat shuffle available.

## 0.11.1
- Prior release.
