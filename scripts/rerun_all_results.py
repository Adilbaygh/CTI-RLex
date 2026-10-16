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

One step, the network map of Figure 1, needs the raw open-data layers rather than the
published benchmarks. It is skipped, with a line saying so, unless LEXIMIN_DATASETS points at
that root; every other step runs for a reader who has the repository alone.

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
    (6, "component-level analysis of the county instance",
     ("scripts/component_analysis.py",)),
    (7, "audit layer of the county instance",
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

# Steps 15 to 24: the measurements the reviewers asked for. Steps 15 to 17 are the third
# reviewer's; steps 18 and 19 answer Reviewer 1, point 2.2: the three-claimant instance
# against the canal flows measured in 2025, and the same instance re-solved with each
# claimant's demand set to its measured diversion. Step 20 answers point 2.1: both instances
# with CTI-RLex subordinated to the decree priority of the claimants' water rights. Steps 21
# and 22 answer point 1.2: the guarantees on the convex hull of the scenarios, and the
# three-claimant guarantees in the river's seasons of 1993 to 2025. Step 23 answers Reviewer 2
# and Reviewer 1, point 1.4: both instances with canal conveyance losses two, four and six times
# the published rate. Step 24 returns to point 2.1 with priority tiers assigned to rights rather
# than to claimants, a post hoc analysis. Each reads only the released benchmarks and, for
# steps 18 to 24, the observations, water-right records and gauge record kept beside them, so
# they can run in any order; they come after the experiments because they are the longest
# steps after the factorial design.
REVIEW_STEPS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (15, "optimality certificates, tolerance grid and near-tied levels",
     ("scripts/numerical_certificates.py",)),
    (16, "what the objective hierarchy determines, and the comparators' faces",
     ("scripts/flow_uniqueness.py",)),
    (17, "monotone realization across nested scenarios",
     ("scripts/monotone_realization.py",)),
    (18, "the three-claimant instance against the canal flows measured in 2025",
     ("scripts/station_comparison.py",)),
    (19, "the three-claimant instance with demand set to the measured diversions",
     ("scripts/observed_demand_sensitivity.py",)),
    (20, "the priority comparator PRIOR-LEX on both instances",
     ("scripts/prior_lex.py",)),
    (21, "the guarantees on the convex hull of the scenarios, both instances",
     ("scripts/robust_vertex_check.py",)),
    (22, "the three-claimant guarantees in the seasons of 1993 to 2025",
     ("scripts/historical_reliability.py",)),
    (23, "both instances with larger canal conveyance losses",
     ("scripts/conveyance_loss_levels.py",)),
    (24, "PRIOR-LEX with priority tiers assigned to rights (post hoc)",
     ("scripts/prior_lex_rights.py",)),
)

# Steps 26 to 29: these read what everything above wrote, so they come last.
CLOSING_STEPS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (26, "published CSV tables and figures", ("scripts/create_results_artifacts.py",)),
    (27, "Figure 4", ("scripts/update_figure4_two_panel.py",)),
    (28, "figure map, resolution, printed type size and greyscale check",
     ("scripts/verify_publication_figures.py",)),
    (29, "machine and solver versions", ("scripts/record_environment.py",)),
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
    cache = revision["cache_valley_v4"]
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
         [0.0689, 0.0564], "{:.4f}"),
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
        if (row["claimants"], row["scenarios"]) in {(2, 5), (15, 1), (15, 5), (3, 5)}:
            print(f"    S14 {row['benchmark']:16s} K={row['claimants']:2d} S={row['scenarios']}   "
                  f"{row['runtime_s']:.3f} s" + spread(row))
    print(f"    revision, Cache Valley solve   {cache['cti_rlex']['runtime_s']:.3f} s")
    print("")
    print(f"  machine: {environment['processor']}, {environment['logical_cores']} cores, "
          f"{environment['operating_system']}")
    print(f"           Python {environment['python']}, NumPy {environment['numpy']}, "
          f"SciPy {environment['scipy']}")
    review_summary()
    return drifted


def review_summary() -> None:
    """Print the measurements of steps 15 to 24, which the revised article will quote.

    They are not compared with anything yet: the article that prints them is being written
    from these files. Once it is, the values it commits to belong among the invariants above.
    """

    certificates = json.loads((RESULTS / "numerical_certificates.json").read_text(encoding="utf-8"))
    uniqueness = json.loads((RESULTS / "flow_uniqueness.json").read_text(encoding="utf-8"))
    monotone = json.loads((RESULTS / "monotone_realization.json").read_text(encoding="utf-8"))
    stations = json.loads((RESULTS / "station_comparison.json").read_text(encoding="utf-8"))
    measured = json.loads((RESULTS / "observed_demand_sensitivity.json").read_text(encoding="utf-8"))
    priority = json.loads((RESULTS / "prior_lex.json").read_text(encoding="utf-8"))
    hull = json.loads((RESULTS / "robust_vertex_check.json").read_text(encoding="utf-8"))
    history = json.loads((RESULTS / "historical_reliability.json").read_text(encoding="utf-8"))
    losses = json.loads((RESULTS / "conveyance_loss_levels.json").read_text(encoding="utf-8"))
    rights = json.loads((RESULTS / "prior_lex_rights.json").read_text(encoding="utf-8"))
    print("")
    print("  measured for the reviewers (steps 15 to 24)")
    for name, item in certificates["instances"].items():
        grid, tie = item["grid"], item["near_tie"]
        closest = item["closest_distinct_levels"]["closest_distance"]
        print(f"    {name:16s} certificates: {item['certificates']['linear_programs']} LPs, "
              f"relative gap <= {item['certificates']['max_relative_gap']:.1e}, "
              f"dual residual <= {item['certificates']['max_dual_residual']:.1e}")
        retried = grid.get("failed_because_a_program_returned_no_optimum", 0)
        print(f"    {'':16s} tolerance grid: {grid['points']} points, {len(grid['failed'])} failed "
              f"({retried} with a program returning no optimum, {grid.get('of_those_completed_with_fallbacks', 0)} "
              f"of them complete with fallbacks, largest shift "
              f"{grid.get('max_guarantee_shift_of_points_completed_with_fallbacks')}), "
              f"largest guarantee shift {grid['max_guarantee_shift']:.1e} "
              f"({grid['max_guarantee_shift_with_every_tolerance_at_most_1e-6']:.1e} with every tolerance <= 1e-6), "
              f"four decimals everywhere: {grid['every_point_agrees_at_four_decimals']}")
        print(f"    {'':16s} near tie: separated above 10x tolerance: "
              f"{tie['separated_whenever_the_measured_distance_exceeds_ten_times_the_tolerance']}, merged at or "
              f"below it: {tie['merged_whenever_the_measured_distance_is_at_most_the_tolerance']}; "
              f"closest distinct levels {closest if closest is None else f'{closest:.4f}'}")
    for name, item in uniqueness["instances"].items():
        families = item["cti_rlex"]["families"]
        cells, sources = families["period_service_ratio"], families["source_seasonal_injection_af"]
        print(f"    {name:16s} undetermined: {cells['undetermined']} of {cells['quantities']} cells "
              f"(widest {cells['largest_undetermined_width']:.3f}), {sources['undetermined']} of "
              f"{sources['quantities']} source totals (widest {sources['largest_undetermined_width']:.1f} acre-ft); "
              f"unresolved: {item['cti_rlex']['unresolved_quantities']}; "
              f"repeat identical: {item['reproducibility']['repeated_solve_is_identical_value_for_value']}")
        for rule, comparator in item["comparators"].items():
            best = comparator["most_favorable_sorted_vector_on_the_face"]
            print(f"    {'':16s} {rule}: realized guarantees determined: "
                  f"{comparator['every_realized_guarantee_is_determined']}; most favorable sorted vector "
                  f"{best if best is None else [round(value, 4) for value in best]}"
                  + (f" (blocking tolerance {comparator['most_favorable_vector_blocking_tolerance']:g})"
                     if comparator.get("most_favorable_vector_blocking_tolerance") else ""))
    for name, item in monotone["instances"].items():
        fixed = item.get("with_the_published_guarantee_vector", {})
        print(f"    {name:16s} monotone realization on the face: "
              f"{item['a_monotone_realization_exists_on_the_published_face']} (least violation "
              f"{item['least_total_violation_on_the_published_face_af']:.1f} acre-ft); with the vector fixed: "
              f"nominal cost {round(fixed.get('nominal_delivery_cost_af', float('nan')), 1) + 0.0:.1f}, "
              f"contingency cost {round(fixed.get('weighted_contingency_delivery_cost_af', float('nan')), 1) + 0.0:.1f} "
              f"acre-ft")
    print(f"    observed 2025 canal flows (Reviewer 1, 2.2): every month agrees with the viewer's monthly "
          f"summary: {stations['every_2025_month_agrees_with_the_viewer_summary']}")
    for station, verdict in stations["hypothesis_H_2_2"].items():
        tested = len(verdict["tested_months"])
        print(f"    {'':16s} station {station} at {verdict['compared_at']}: within a factor of two of the plan in "
              f"{verdict['months_within_factor_of_plan']}/{tested} months, of the requirement in "
              f"{verdict['months_within_factor_of_requirement']}/{tested}; peak {verdict['observed_peak_month']}")
    print("    demand set to the measured 2025 diversions (Reviewer 1, 2.2):")
    for name, variant in measured["variants"].items():
        methods, item = variant["methods"], variant["indicators"]
        print(f"    {'':16s} {name}: CTI-RLex {[round(value, 4) for value in methods['CTI-RLex proposed']['sorted']]}, "
              f"PROP-BR {[round(value, 4) for value in methods['PROP-BR']['sorted']]}, UTIL-BR minimum "
              f"{methods['UTIL-BR']['minimum_guarantee']:.4f}; price of fairness {item['price_of_fairness_percent']:.2f}%, "
              f"value of recourse {item['value_of_recourse_absolute']:.4f}, robustness cost {item['robustness_cost_percent']:.1f}%")
    print("    CTI-RLex subordinated to decree priority (Reviewer 1, 2.1):")
    for name, item in priority["instances"].items():
        for variant, comparison in item["against_cti_rlex"].items():
            moved = {claimant: round(change, 4) for claimant, change in comparison["claimants_that_moved"].items()}
            print(f"    {name:16s} {variant}: tiers {[len(tier) for tier in comparison['tiers']]}, minimum "
                  f"{comparison['minimum_guarantee']['CTI-RLex']:.4f} -> {comparison['minimum_guarantee']['PRIOR-LEX']:.4f}, "
                  f"moved {moved or 'none'}, nominal {comparison['nominal_delivery_change_af']:+.1f} acre-ft")
    print("    guarantees on the convex hull of the scenarios, plan fixed (Reviewer 1, 1.2):")
    for name, item in hull["instances"].items():
        combinations = item["combinations"]
        print(f"    {name:16s} {combinations['count']} combinations: smallest share of the guarantee "
              f"{combinations['smallest_share']:.9f}, {combinations['below_full_guarantee']} below 1; every "
              f"scenario delivers it: {item['every_scenario_delivers_the_full_guarantee']}")
    print("    the three-claimant guarantees in the seasons of 1993 to 2025, plan fixed (Reviewer 1, 1.2):")
    for name, summary in history["summary"].items():
        rates = {claimant: f"{rate:.0%}" for claimant, rate in summary["reliability"].items()}
        print(f"    {'':16s} {name}: every promise kept in {summary['system_reliability']:.0%} of the years; "
              f"by claimant {rates}; years beyond budget {summary['years_beyond_budget'] or 'none'}")
    expectations = history["expectations"]
    print(f"    {'':16s} Paradise-Highline common service: severe {expectations['severe_paradise_highline_common_service']:.4f}, "
          f"lowest year {expectations['driest_year_for_paradise_highline']} "
          f"{expectations['lowest_year_paradise_highline_common_service']:.4f}")
    print("    canal conveyance losses times k (Reviewer 2; Reviewer 1, 1.4):")
    for name, item in losses["instances"].items():
        for k, level in item["levels"].items():
            methods = level["methods"]
            print(f"    {name:16s} k={k}: median route efficiency {level['route_conveyance_efficiency']['median']:.3f}, "
                  f"CTI-RLex minimum {methods['CTI-RLex']['minimum_guarantee']:.4f}, UTIL-BR minimum "
                  f"{methods['UTIL-BR']['minimum_guarantee']:.4f}, first difference from PROP-BR at "
                  f"{level['cti_rlex_against_prop_br']['first_differing_position']}, price of fairness "
                  f"{level['price_of_fairness_percent']:.2f}%")
    print("    PRIOR-LEX with tiers assigned to rights (Reviewer 1, 2.1; post hoc):")
    for name, item in rights["instances"].items():
        moved = {claimant: round(change, 4) for claimant, change in item["change_against_claimant_level_prior_lex"].items()
                 if abs(change) > 1e-4}
        print(f"    {name:16s} split {sorted(item['split_claimants']) or 'none'}; moved against claimant-level "
              f"PRIOR-LEX {moved or 'none'}; least served {item['least_served']} at {item['minimum_guarantee']:.4f}")


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

    # The county benchmark reads every official path as the set of reaches it lists, so no
    # connector is rejected and no service area is excluded; the repair-order and excluded-
    # area analyses of version 3 have nothing left to measure. What replaces them is the
    # record of what the reading changed, and it needs only the released benchmark.
    started = step(14, "path reading of the county instance")
    run("scripts/path_reading_table.py")
    done(started)

    for number, title, arguments in REVIEW_STEPS:
        began = step(number, title)
        run(*arguments)
        done(began)

    started = step(25, "benchmark network map (Figure 1)")
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

    started = step(30, "test suite")
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
