"""Default entry point. The GUI ships in Phase 3 — for now this dispatches
to the CLI when given any arg, or prints a hint."""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"index", "list", "info"}:
        from .cli import main as cli_main
        return cli_main(sys.argv[1:])
    from .app import launch
    launch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
