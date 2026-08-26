"""Desktop entry point for the CTI-RLex graphical application."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the CTI-RLex desktop GUI.")
    parser.add_argument(
        "--benchmark",
        type=Path,
        help="Benchmark JSON to open instead of the project default.",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        help="Render one off-screen GUI screenshot and exit (for visual testing).",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=0,
        help="Zero-based page index used with --screenshot.",
    )
    parser.add_argument(
        "--language",
        choices=("uz", "en"),
        help="Initial GUI language; otherwise the saved preference is used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    try:
        from leximin.gui.app import launch
    except ImportError as exc:
        if exc.name and exc.name.startswith("PyQt6"):
            print(
                "CTI-RLex GUI requires PyQt6. Install it with:\n"
                "  python -m pip install -e .[gui]",
                file=sys.stderr,
            )
            return 2
        raise

    return launch(
        project_root=ROOT,
        benchmark=args.benchmark,
        screenshot=args.screenshot,
        page_index=args.page,
        language=args.language,
    )


if __name__ == "__main__":
    raise SystemExit(main())
