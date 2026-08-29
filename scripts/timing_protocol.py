"""One timing protocol for every published measurement.

Solve times were previously measured three different ways: the scalability sweep and the
method comparison took the median of three repeats, while the 135-case factorial timed a
single solve. The same configuration could therefore be reported with two different
numbers in two different tables, which is what a reviewer found.

Every published timing now goes through this module, so the manuscript, the Supplementary
Material and the machine-readable result files describe the same measurement. The median
is the reported value; the minimum and maximum travel with it so that a table can show the
spread instead of implying a precision the measurement does not have.

Timings are machine-dependent by nature. Run the producing scripts on the machine whose
description `scripts/record_environment.py` writes into `results/environment.json`, and
rerun every producer together, so that one environment stands behind every reported time.
"""

from __future__ import annotations

from statistics import median
from time import perf_counter
from typing import Any, Callable

#: Repeats behind every published timing. Raise it for a quieter measurement; the value is
#: recorded in each result file so a reader can tell what the reported median rests on.
REPEATS = 5


def summarize(runtimes: list[float]) -> dict[str, Any]:
    """The reported statistics for one measured configuration."""

    if not runtimes:
        raise ValueError("no runtimes to summarize")
    return {
        "repeats": len(runtimes),
        "median_runtime_seconds": median(runtimes),
        "min_runtime_seconds": min(runtimes),
        "max_runtime_seconds": max(runtimes),
        "runtime_seconds_repeats": list(runtimes),
    }


def timed(call: Callable[[], Any], repeats: int = REPEATS) -> tuple[Any, dict[str, Any]]:
    """Run ``call`` ``repeats`` times and return its last result with the timing summary."""

    runtimes: list[float] = []
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = call()
        runtimes.append(perf_counter() - started)
    return result, summarize(runtimes)
