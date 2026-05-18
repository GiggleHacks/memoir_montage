# Changelog

All notable changes to memoir_montage. Bump the version in `pyproject.toml` and
`compilation_maker/__init__.py` for every user-facing change.

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
