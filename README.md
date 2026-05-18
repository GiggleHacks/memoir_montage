# Compilation Maker

Point it at a folder of videos. It indexes them (with content filters), then renders an NxN simultaneous-playback collage where random clips swap every few seconds.

Cyberpunk command-center GUI. Local, no cloud, no API keys.

## Status

Phase 1: indexing + analyzers + CLI. GUI and compile pipeline land in later phases.

## Install (dev)

```
cd D:\vibe\compilation_maker
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

First indexing run will download model weights (NudeNet ONNX, MediaPipe TFLite, Silero VAD ONNX) into the appropriate package caches — ~150 MB total.

## CLI usage

```
# Index a folder (recursive). Cached after first run.
python -m compilation_maker.cli index "G:\robvideos\Videos"

# List eligible videos with current filter settings
python -m compilation_maker.cli list "G:\robvideos\Videos" --show-all

# Same but ignore filters (show everything indexed)
python -m compilation_maker.cli list "G:\robvideos\Videos" --no-filters --limit 20

# Dump the cache row for a single file
python -m compilation_maker.cli info "G:\robvideos\Videos\trip.mp4"
```

## Settings

`%APPDATA%\CompilationMaker\settings.json` — toggles and thresholds. Created on first save; defaults are baked into `compilation_maker/settings.py`.

## Cache

`%APPDATA%\CompilationMaker\index.sqlite`. Safe to delete to force a full re-index.

## Tests

```
pytest tests\
```
