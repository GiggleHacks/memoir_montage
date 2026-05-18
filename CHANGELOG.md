# Changelog

All notable changes to memoir_montage. Bump the version in `pyproject.toml` and
`compilation_maker/__init__.py` for every user-facing change.

## 0.12.5 — 2026-05-18
- Chronological and No-Repeat modes now strictly never repeat a clip. If the
  pool can't fill the requested length, segments are trimmed off the end
  (output gets shorter) instead of looping back to the start of the pool.
  A warning is logged showing the actual output length vs requested.
- Random mode keeps the wrap-and-reuse behavior since repeats are expected
  there.

## 0.12.4 — 2026-05-18
- Cap grid size at 6×6 (36 cells). 7×7 and larger reliably crash ffmpeg with
  "Generic error in an external library" — too many simultaneous decodes +
  xstack + amix inputs for a single ffmpeg invocation. Until we add a
  multi-pass / pre-rendered tile path, only safe grids are exposed.
- Add 2×2 as the new floor option.

## 0.12.3 — 2026-05-18
- When a segment render fails, the activity log now lists every input clip
  used in that segment so you can isolate the bad file.
- Add `-fflags +discardcorrupt+genpts` and `-err_detect ignore_err` to inputs
  so one flaky clip is more likely to be skipped instead of killing the
  whole segment.

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
