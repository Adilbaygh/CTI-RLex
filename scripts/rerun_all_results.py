"""Re-run every published result producer under one timing protocol.

Solve times once disagreed between the manuscript, the Supplementary Material and the
archived JSON files, because the three came from three separate measurement runs. Every
producer now times through scripts/timing_protocol.py, so one run of this script leaves a
single, self-consistent set of numbers behind.

This replaces the PowerShell version, which only a Windows reader could run: its commands
were written with backslash paths and backtick continuations, so the first line of it fails
in bash and in zsh. Everything here goes through pathlib and sys.executable, so the same
file runs on Windows, macOS and Linux.

Run it from the repository root, on the machine whose description belongs in the article:

    python scripts/rerun_all_results.py

Add --dry-run to print the sequence and check that every script it names exists, without
running anything: a real rerun rewrites every timing in results/, and the manuscript quotes
them, so it belongs at the point where the documents are regenerated too.

Two steps need the raw open-data layers rather than the published benchmarks. They are
skipped, with a line saying so, unless LEXIMIN_DATASETS points at that root; every other
step runs for a reader who has the repository alone.

It writes only into results/. It does not commit and does not push.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"
LITTLE_BEAR = "DATA/LittleBearRiver_2025_Benchmark"

# Set once and inherited by every step, so a reader who has not installed the package still
# gets the library from src/ rather than whatever happens to be on the machine.
ENVIRONMENT = dict(os.environ)
ENVIRONMENT["PYTHONPATH"] = os.pathsep.join(
    [str(REPO / "src"), ENVIRONMENT.get("PYTHONPATH", "")]
).strip(os.pathsep)

DATASETS = ENVIRONMENT.get("LEXIMIN_DATASETS", "")

# Steps 3 to 13: one producer each, in the order the later ones need the earlier output.
MIDDLE_STEPS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (3, "effect decomposition of the factorial design",
     ("scripts/factorial_decomposition.py",)),
    (4, "residual, feasibility and terminal-representation audits",
     ("scripts/run_cti_verification.py", f"{LITTLE_BEAR}/benchmark.json",
      "--output", "results/cti_rlex_verification.json")),
    (5, "lexicographic vector against a common floor",
     ("scripts/revision_experiments.py",)),
    (6, "component-level analysis of the ten-claimant instance",
     ("scripts/component_analysis.py",)),
    (7, "audit layer of the ten-claimant instance",
     ("scripts/cache_valley_audit.py",)),
    (8, "parameter provenance and coefficient tables",
     ("scripts/benchmark_parameter_tables.py",)),
    (9, "source-removal ablation on both instances",
     ("scripts/ablation_experiment.py",)),
    (10, "guarantee vector under three recourse-budget regimes",
     ("scripts/equal_budget_experiment.py",)),
    (11, "guarantee vector under three effort-coefficient weightings",
     ("scripts/normalization_sensitivity.py",)),
    (12, "canal-restriction severity sweep",
     ("scripts/restriction_threshold_experiment.py",)),
    (13, "scalability sweep",
     ("scripts/scalability_experiment.py",)),
)

# Steps 16 to 19: these read what everything above wrote, so they come last.
CLOSING_STEPS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (16, "published CSV tables and figures", ("scripts/create_results_artifacts.py",)),
    (17, "Figure 4", ("scripts/update_figure4_two_panel.py",)),
    (18, "figure map, resolution, printed type size and greyscale check",
     ("scripts/verify_publication_figures.py",)),
    (19, "machine and solver versions", ("scripts/record_environment.py",)),
)


DRY_RUN = "--dry-run" in sys.argv[1:]


def run(*arguments: str) -> None:
    """Run one producer, and stop the whole rerun if it fails.

    A rerun that carries on past a failed step leaves results/ holding a mixture of two
    runs, which is exactly the inconsistency this script exists to prevent.

    Under --dry-run the command is printed and the file it names is checked to exist, but
    nothing is executed. That is the safe way to see that the sequence is intact on a
    machine whose results/ already backs a finished manuscript: a real rerun rewrites every
    timing, and the documents quote them.
    """

    print("   python -B " + " ".join(arguments))
    if DRY_RUN:
        target = arguments[0]
        if not target.startswith("-") and not (REPO / target).exists():
            raise SystemExit(f"   missing: {target}")
        return
    finished = subprocess.run([sys.executable, "-B", *arguments], cwd=REPO, env=ENVIRONMENT)
    if finished.returncode != 0:
        raise SystemExit(f"   step failed with exit code {finished.returncode}")


def step(number: int, title: str) -> float:
    print(f"\n=== {number}. {title} ===")
    return time.perf_counter()


def done(started: float) -> None:
    print(f"   done in {time.perf_counter() - started:.1f} s")


def summary() -> list[tuple[str, str, str]]:
    """Check the values a correct rerun must reproduce, and print the ones it may not.

    Guarantees, prices and ratios are properties of the linear programs and must not move;
    timings are properties of the machine and will. Separating them lets a reader see at a
    glance whether a rerun changed anything that matters.

    Until this was corrected the invariants were printed beside the words "expected
    0.4195" and never compared with them, so a rerun that moved one of them scrolled past
    and the script still exited zero.

    Each invariant is compared at the precision the article commits to: half of its last
    printed digit. That is the right threshold in both directions. Tighter would report a
    difference the article does not claim -- the utilitarian guarantee is 0.10765061, and
    the article's 0.1077 is a rounding of it -- and looser would let a real change through.
    What moved is returned so that the caller can fail on it.
    """

    experiments = json.loads((RESULTS / "cti_rlex_experiments.json").read_text(encoding="utf-8"))
    verification = json.loads((RESULTS / "cti_rlex_verification.json").read_text(encoding="utf-8"))
    revision = json.loads((RESULTS / "revision_experiments.json").read_text(encoding="utf-8"))
    scalability = json.loads((RESULTS / "scalability_cache_valley.json").read_text(encoding="utf-8"))
    environment = json.loads((RESULTS / "environment.json").read_text(encoding="utf-8"))

    methods = {row["method"]: row for row in experiments["method_comparison"]}
    util, rlex = methods["UTIL-BR"], methods["CTI-RLex proposed"]
    rigid, nominal = methods["CTI-RLex rigid"], methods["CTI-RLex nominal only"]
    cache = revision["cache_valley_v3"]
    factorial = [case["minimum_guarantee"] for case in experiments["sensitivity"]]
    sorted_base = sorted(verification["base_guarantees"].values())

    def share(larger: float, smaller: float) -> float:
        return 100.0 * (larger - smaller) / larger

    # label, measured values, the values the article prints, and the format both are shown
    # in. The tolerance is half the last digit of that format.
    invariants: tuple[tuple[str, list[float], list[float], str], ...] = (
        ("three-claimant vector", sorted_base, [0.4195, 0.4195, 0.4477], "{:.4f}"),
        ("UTIL-BR minimum guarantee", [util["minimum_guarantee"]], [0.1077], "{:.4f}"),
        ("CTI-RLex minimum guarantee", [rlex["minimum_guarantee"]], [0.4195], "{:.4f}"),
        ("CTI-RLex rigid guarantee", [rigid["minimum_guarantee"]], [0.3841], "{:.4f}"),
        ("sigma_2 CTI-RLex / PROP-BR",
         [cache["cti_rlex"]["sorted_rho"][1], cache["prop_br"]["sorted_rho"][1]],
         [0.1374, 0.0564], "{:.4f}"),
        ("price of fairness",
         [share(util["nominal_beneficial_delivery_af"],
                rlex["nominal_beneficial_delivery_af"])], [2.57], "{:.2f}%"),
        ("value of recourse",
         [100.0 * (rlex["minimum_guarantee"] - rigid["minimum_guarantee"])
          / rigid["minimum_guarantee"]], [9.22], "{:.2f}%"),
        ("robustness cost",
         [share(nominal["nominal_beneficial_delivery_af"],
                rlex["nominal_beneficial_delivery_af"])], [31.5], "{:.1f}%"),
        ("factorial range", [min(factorial), max(factorial)],
         [0.2243, 0.7011], "{:.4f}"),
    )

    drifted: list[tuple[str, str, str]] = []
    print("  these must NOT have changed")
    for label, measured, published, shape in invariants:
        decimals = int(shape.split(".")[1][0])
        tolerance = 0.5 * 10 ** -decimals
        shown = " ".join(shape.format(value) for value in measured)
        wanted = " ".join(shape.format(value) for value in published)
        moved = len(measured) != len(published) or any(
            abs(value - target) > tolerance for value, target in zip(measured, published)
        )
        if moved:
            drifted.append((label, shown, wanted))
        print(f"    [{'MOVED' if moved else 'ok':>5}] {label:<28}{shown:<22}"
              f"the article prints {wanted}")

    print("")
    print("  these ARE expected to change - the timings being fixed")

    def spread(row: dict) -> str:
        low, high = row.get("min_runtime_seconds"), row.get("max_runtime_seconds")
        if low is None or high is None:
            return "   (no spread recorded - old protocol)"
        return f"   range {low:.3f}-{high:.3f} over {row.get('repeats')} repeats"

    for row in experiments["scalability"]:
        constraints = row["equality_constraints"] + row["inequality_constraints"]
        count = row["scenario_count"]
        label = f"{count} scenario" if count == 1 else f"{count} scenarios"
        print(f"    Table 6, {label:12s}{row['variables']:4d} var; "
              f"{constraints:4d} con; {row['median_runtime_seconds']:.3f} s" + spread(row))
    for row in scalability:
        if (row["claimants"], row["scenarios"]) in {(2, 5), (10, 1), (10, 5), (3, 5)}:
            print(f"    S14 {row['benchmark']:16s} K={row['claimants']:2d} S={row['scenarios']}   "
                  f"{row['runtime_s']:.3f} s" + spread(row))
    print(f"    revision, Cache Valley solve   {cache['cti_rlex']['runtime_s']:.3f} s")
    print("")
    print(f"  machine: {environment['processor']}, {environment['logical_cores']} cores, "
          f"{environment['operating_system']}")
    print(f"           Python {environment['python']}, NumPy {environment['numpy']}, "
          f"SciPy {environment['scipy']}")
    return drifted


def main() -> None:
    if not (REPO / "scripts" / "timing_protocol.py").exists():
        raise SystemExit(f"Run this from the repository root ({REPO}).")

    opened = time.perf_counter()
    print("\n=== environment ===")
    run("-c", "import sys, numpy, scipy; print('python', sys.version.split()[0], "
              "'| numpy', numpy.__version__, '| scipy', scipy.__version__)")
    run("-c", "import sys; sys.path.insert(0, 'scripts'); import timing_protocol as t; "
              "print('timing repeats:', t.REPEATS)")

    started = step(1, "base solution")
    run("scripts/run_cti_rlex.py", f"{LITTLE_BEAR}/benchmark.json",
        "--output", "results/cti_rlex_base.json")
    done(started)

    started = step(2, "comparators, ablation, factorial and scalability")
    run("scripts/run_cti_experiments.py", f"{LITTLE_BEAR}/benchmark.json",
        "--sensitivity-cases", f"{LITTLE_BEAR}/data/sensitivity_cases.csv",
        "--output", "results/cti_rlex_experiments.json")
    done(started)

    for number, title, arguments in MIDDLE_STEPS:
        began = step(number, title)
        run(*arguments)
        done(began)

    started = step(14, "acyclicity-repair order sensitivity and excluded service areas")
    if DATASETS:
        run("scripts/excluded_service_areas.py")
        run("scripts/connector_order_experiment.py", "--build", "--rebuild")
    else:
        print("   skipped: these rebuild from the raw Utah layers; set LEXIMIN_DATASETS "
              "to the open-data root first")
    done(started)

    started = step(15, "benchmark network map (Figure 1)")
    # The only producer that needs the open Utah layers rather than the published
    # benchmark. A reader who has the repository but not the layers keeps every other step.
    if DATASETS and Path(DATASETS).exists():
        run(f"{LITTLE_BEAR}/plot_benchmark_map.py")
    else:
        print("   skipped: set LEXIMIN_DATASETS to the open-layer root to redraw Figure 1")
    done(started)

    for number, title, arguments in CLOSING_STEPS:
        began = step(number, title)
        run(*arguments)
        done(began)

    started = step(20, "test suite")
    run("-m", "pytest", "-q")
    done(started)

    if DRY_RUN:
        print("\ndry run: every step above resolved to a file that exists, and nothing ran.")
        return

    print("\n=== key numbers ===")
    drifted = summary()

    print("\n=== files git sees as changed ===")
    subprocess.run(["git", "status", "--short"], cwd=REPO)

    print(f"\nfinished in {time.perf_counter() - opened:.1f} s. "
          "Nothing was committed and nothing was pushed.")

    # A rerun whose invariants moved is not a successful rerun, whatever else it printed.
    # Exiting non-zero is what makes this usable from a shell script or a CI job.
    if drifted:
        raise SystemExit(
            f"\n{len(drifted)} published value(s) moved:\n"
            + "\n".join(f"    {label}: this run gives {shown}, the article prints {wanted}"
                        for label, shown, wanted in drifted)
            + "\n  results/ and the article now disagree. Nothing was committed; find the "
              "cause before this run is used."
        )


if __name__ == "__main__":
    main()
