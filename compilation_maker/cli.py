"""Headless CLI for testing without the GUI.

    python -m compilation_maker.cli index <folder>
    python -m compilation_maker.cli list  <folder> [--show-all] [--no-filters]
    python -m compilation_maker.cli info  <file>
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Force UTF-8 on stdout so Unicode glyphs (·, ✗, ↺, →) survive Windows consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

from .events import Control, EventBus
from .index.cache import Cache
from .index.indexer import scan_tree
from .compile.selector import select
from .settings import load as load_settings, resolve_filters


_LEVEL_COLOR = {
    "info": "\033[36m",
    "ok": "\033[32m",
    "warn": "\033[33m",
    "err": "\033[31m",
}
_RESET = "\033[0m"


def _print_event(ev: tuple) -> None:
    tag = ev[0]
    if tag == "log":
        _, msg, level = ev
        color = _LEVEL_COLOR.get(level, "")
        print(f"{color}[{level:>4}]{_RESET} {msg}")
    elif tag == "current":
        _, path, sub = ev
        print(f"  -> {Path(path).name}  ({sub})")
    elif tag == "counts":
        _, done, total, rate, eta = ev
        sys.stdout.write(f"\r    {done}/{total}  rate={rate:.1f}/s  eta={eta}        ")
        sys.stdout.flush()
    elif tag == "done":
        print()
        print(f"DONE: {ev[1]}")
    elif tag == "phase":
        pass  # not interesting in CLI
    elif tag == "analysis":
        pass
    else:
        print(ev)


def _drain(bus: EventBus, control: Control) -> None:
    while True:
        ev = bus.get(timeout=0.25)
        if ev is None:
            if control.stop.is_set():
                break
            continue
        _print_event(ev)
        if ev[0] == "done":
            break


def cmd_index(args: argparse.Namespace) -> int:
    settings = load_settings()
    bus = EventBus()
    control = Control.new()
    cache = Cache()

    import threading
    th = threading.Thread(
        target=scan_tree,
        args=(Path(args.folder), bus, control),
        kwargs={"cache": cache, "settings": settings},
        daemon=True,
    )
    th.start()
    try:
        while th.is_alive():
            ev = bus.get(timeout=0.5)
            if ev is not None:
                _print_event(ev)
                if ev[0] == "done":
                    break
        th.join()
    except KeyboardInterrupt:
        control.stop.set()
        th.join()
        print("\ncancelled.")
    # drain remaining events
    for ev in bus.drain():
        _print_event(ev)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    settings = load_settings()
    cache = Cache()
    if args.no_filters:
        settings["filters"] = {"preset": "off"}
    filters = resolve_filters(settings)
    eligible = select(cache, Path(args.folder), filters=filters, thresholds=settings["thresholds"])
    print(f"{len(eligible)} eligible videos under {Path(args.folder).resolve()}")
    if args.show_all or args.limit:
        n = args.limit if args.limit else None
        for e in eligible[:n] if n else eligible:
            yr = e.created_year if e.created_year else "----"
            print(f"  [{yr}] {e.duration:6.1f}s  {e.path}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    cache = Cache()
    p = str(Path(args.file).resolve())
    rows = [r for r in cache.all() if r["path"] == p]
    if not rows:
        print("not in cache")
        return 1
    r = rows[0]
    for k in r.keys():
        print(f"  {k:>18}: {r[k]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="compilation-maker-cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="Index a folder")
    p_index.add_argument("folder")

    p_list = sub.add_parser("list", help="List eligible videos in a folder")
    p_list.add_argument("folder")
    p_list.add_argument("--show-all", action="store_true")
    p_list.add_argument("--no-filters", action="store_true")
    p_list.add_argument("--limit", type=int, default=0)

    p_info = sub.add_parser("info", help="Show cache row for one file")
    p_info.add_argument("file")

    args = ap.parse_args(argv)
    if args.cmd == "index":
        return cmd_index(args)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "info":
        return cmd_info(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
