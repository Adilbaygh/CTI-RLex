"""Rebuild the ten-claimant Cache Valley benchmark in the two passes its construction needs.

Why two passes. The acyclicity repair can remove every route to a service area, and which
areas lose their routes is known only after the repair has run. The shared source groups,
however, are derived from the claimant set: with the fifteen companies that carry irrigated
acreage the weakly connected components merge differently than with the ten that survive, so
a one-pass build produces nine source groups where the published instance has seven, and
claimant records whose terminal node the benchmark no longer contains. The released package
therefore could not rebuild its own benchmark; a reviewer asked for exactly this to be
reproducible.

Pass one builds from every qualifying company and stops as soon as the repair reports
companies without a route, before any benchmark file is written. It leaves
``unrouted_claimants.json`` behind. Pass two reads that report and rebuilds with the
survivors as claimants -- while keeping pass one's path set, so the repair sees the same
candidate connectors and settles on the same graph.

Nothing outside the benchmark directory is edited. ``selection.json`` is the cache the
discovery pass writes, and by default it is only read; ``--rediscover`` deletes it first so
the pass runs again over the raw layers, and the file it writes back must be byte-identical
to the released one. That is the check that the cache is a cache and not a hidden input.

Run:  python scripts/rebuild_cache_valley.py [--rediscover]
Environment: LEXIMIN_DATASETS must point at the open-data root.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO / "DATA" / "LittleBearRiver_2025_Benchmark"
TARGET = REPO / "DATA" / "CacheValley_2025_Benchmark"
SELECTION = TARGET / "selection.json"
# The reconstructed source is preferred; the surviving 3.10 bytecode is the fallback and is
# an older revision -- it names the reference scenario "reference", which the validator no
# longer accepts, and it promotes no head gates to recourse controls.
_SOURCE = BENCHMARK_DIR / "generate_cache_valley_benchmark.py"
_BYTECODE = BENCHMARK_DIR / "generate_cache_valley_benchmark.pyc"
DRIVER = _SOURCE if _SOURCE.exists() else _BYTECODE
# The driver repoints the generator's output directory at the county target, so the first
# pass leaves its report beside the benchmark; older layouts left it next to the generator.
UNROUTED_CANDIDATES = (
    TARGET / "unrouted_claimants.json",
    BENCHMARK_DIR / "unrouted_claimants.json",
)


def unrouted_report() -> Path | None:
    return next((path for path in UNROUTED_CANDIDATES if path.exists()), None)


def run_driver(interpreter: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        interpreter + [str(DRIVER)],
        cwd=BENCHMARK_DIR,
        capture_output=True,
        text=True,
        env={**os.environ},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        nargs="+",
        default=["py"],
        help="interpreter that runs the driver (default: py; use 'py -3.10' for the bytecode)",
    )
    parser.add_argument(
        "--rediscover",
        action="store_true",
        help="delete selection.json first, so the pass over the raw layers runs again; the "
        "rewritten file must come back byte-identical to the released one",
    )
    arguments = parser.parse_args()

    if not DRIVER.exists():
        raise SystemExit(f"driver not found: {DRIVER}")
    if "LEXIMIN_DATASETS" not in os.environ:
        raise SystemExit("set LEXIMIN_DATASETS to the open-data root first")

    # A stale report would make pass one behave like pass two.
    for stale in UNROUTED_CANDIDATES:
        stale.unlink(missing_ok=True)
    if arguments.rediscover:
        SELECTION.unlink(missing_ok=True)
        print(f"removed {SELECTION.name}: the discovery pass will run over the raw layers")

    print("pass 1: building from every qualifying company to learn which lose every route")
    first = run_driver(arguments.python)
    sys.stdout.write(first.stdout)

    if first.returncode == 0:
        print("\npass 1 succeeded: no company lost a route, so one pass was enough.")
        return
    report = unrouted_report()
    if report is None:
        sys.stderr.write(first.stderr)
        raise SystemExit("pass 1 failed for a different reason; nothing was changed")

    dropped = json.loads(report.read_text(encoding="utf-8"))["companies"]
    print(f"\npass 1 identified {len(dropped)} company(ies) without a route:")
    for row in dropped:
        print(f"   - {row['claimant_id']} ({row['name']})")

    print("\npass 2: rebuilding with the survivors as claimants, on pass 1's path set")
    second = run_driver(arguments.python)
    sys.stdout.write(second.stdout)
    if second.returncode != 0:
        sys.stderr.write(second.stderr)
        raise SystemExit("pass 2 failed")
    print("pass 2 succeeded")


if __name__ == "__main__":
    main()
