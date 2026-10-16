"""Out-of-sample reliability of the three-claimant guarantees in the years 1993 to 2025
(Reviewer 1, point 1.2).

Reviewer 1 asked how the guarantees fare under uncertainty that the five deterministic scenarios
do not describe, and suggested Monte Carlo simulation. This script takes the seasons the Little
Bear River actually had: the monthly mean discharge of USGS gauge 10105900, Little Bear River at
Paradise (DATA/USGS_10105900_LittleBearRiver), May to September of 1993 to 2025, the 33 seasons
the record holds in full.

Each year becomes one scenario of the three-claimant instance. The gauge serves as an index of
dryness for the whole system:
  * the limit of each direct diversion and the envelope of each subsystem are scaled, month by
    month, by the ratio of the month's mean discharge to the median of that month over 1993 to
    2025, capped at 1 -- a wet month does not enlarge a canal;
  * the seasonal volume of each reservoir is scaled by the ratio of the year's May-to-September
    volume to the median of those volumes, capped at 1, because a reservoir carries water
    through the season;
  * reservoir outlet capacities, reach capacities, efficiencies and demands are those of the
    published benchmark.
The published nominal plan of CTI-RLex is held fixed and only the bounded recourse answers the
year (scripts/fixed_plan_recourse.py), with the budget of the severe scenario, 0.40: a test out
of sample has to test the plan that was adopted, not one chosen knowing the year. If the plan
cannot be operated within the budget at all, the least effort that operates it is reported and
the budget raised to it.

For each year the claimants' shares of their published guarantees -- the smallest monthly
service ratio over the guarantee, capped at 1 -- are found by progressive filling, so that a
shortfall is shared as CTI-RLex shares one. A claimant's promise is kept in a year when its share
is 1 (within 1e-6) and the plan ran within its budget. Reliability is the fraction of years in
which a promise is kept; its 95% interval comes from 10 000 bootstrap resamples of whole years
with a fixed seed. Two variants vary the design: the budget of the moderate scenario, 0.25, and
the subsystem envelopes left unscaled.

Hypothesis H-1.2 compares the published severe scenario with the driest years: for the
Paradise-Highline subsystem, the largest service ratio that Paradise and Highline reach together
with the plan fixed and budget 0.40 is computed in the severe scenario and in every year.

Two descriptive measures were added after the first run had kept every promise in every year,
which leaves the bootstrap interval with nothing to vary: the exact (Clopper-Pearson) 95%
interval of each reliability, and the headroom of each year and each published scenario -- the
largest multiple of the whole published guarantee vector that it delivers with the plan fixed.

The design was approved by the author and the expectations written before the first run
(requirements/decisions.md and requirements/hypotheses.md, 2026-10-12, H-1.2 and H-1.2b).

Run:  python scripts/historical_reliability.py
Writes: results/historical_reliability.json
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import beta

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import fixed_plan_recourse as fixed  # noqa: E402
from leximin.dag import load_cti_benchmark  # noqa: E402

BENCHMARK = REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"
GAUGE = REPO / "DATA" / "USGS_10105900_LittleBearRiver"
OUTPUT = REPO / "results" / "historical_reliability.json"
YEARS = range(1993, 2026)
SEVERE = "severe_system_shortage"
PARADISE_HIGHLINE = ("company_130", "company_132")
VARIANTS = {
    "budget 0.40": {"budget": 0.40, "scale_envelopes": True},
    "budget 0.25": {"budget": 0.25, "scale_envelopes": True},
    "envelopes unscaled": {"budget": 0.40, "scale_envelopes": False},
}
PRIMARY = "budget 0.40"
KEPT = 1e-6          # a share within this of 1 keeps the promise
OVERRUN = 1e-9       # effort beyond the budget smaller than this is rounding
BOOTSTRAP = 10_000
SEED = 20261012


def read_gauge() -> tuple[dict[int, dict[int, float]], dict]:
    path = GAUGE / "10105900_monthly_mean_discharge.rdb"
    provenance = json.loads((GAUGE / "provenance.json").read_text(encoding="utf-8"))
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != provenance["sha256"]:
        raise SystemExit(f"{path} has SHA-256 {digest}, its provenance records {provenance['sha256']}")
    rows = [line.split("\t") for line in raw.decode("ascii").splitlines() if line and not line.startswith("#")]
    header, rows = rows[0], rows[2:]
    year, month, mean = header.index("year_nu"), header.index("month_nu"), header.index("mean_va")
    flows: dict[int, dict[int, float]] = {}
    for row in rows:
        flows.setdefault(int(row[year]), {})[int(row[month])] = float(row[mean])
    return flows, {"file": str(path.relative_to(REPO)).replace("\\", "/"), "sha256": digest,
                   "retrieved": provenance["retrieved"]}


def dryness(flows, months: dict[str, int], days: dict[str, int]) -> dict:
    """Monthly ratios to the 1993-2025 monthly medians, and the seasonal volume ratio."""

    for year in YEARS:
        missing = [m for m in months.values() if m not in flows.get(year, {})]
        if missing:
            raise SystemExit(f"{year}: no monthly mean for months {missing}")
    median = {m: statistics.median(flows[y][m] for y in YEARS) for m in months.values()}
    volume = {y: sum(days[p] * flows[y][m] for p, m in months.items()) for y in YEARS}
    median_volume = statistics.median(volume.values())
    return {
        "median_cfs_by_month": median,
        "median_season_cfs_days": median_volume,
        "years": {
            y: {
                "monthly_ratio": {p: flows[y][m] / median[m] for p, m in months.items()},
                "seasonal_ratio": volume[y] / median_volume,
            }
            for y in YEARS
        },
    }


def year_parameters(model, nominal: dict, ratios: dict, variant: dict) -> dict:
    surface = {s.source_id for s in model.sources if s.source_class == "surface_diversion"}
    factor = {p: min(1.0, r) for p, r in ratios["monthly_ratio"].items()}
    season = min(1.0, ratios["seasonal_ratio"])
    limit = {(p, s): number * (factor[p] if s in surface else 1.0)
             for (p, s), number in nominal["source_limit"].items()}
    seasonal = {s: (sum(limit[p, s] for p in model.periods) if s in surface else number * season)
                for s, number in nominal["source_seasonal_limit"].items()}
    shared = {(p, g): number * (factor[p] if variant["scale_envelopes"] else 1.0)
              for (p, g), number in nominal["shared_source_limit"].items()}
    return {"edge_capacity": dict(nominal["edge_capacity"]), "source_limit": limit,
            "source_seasonal_limit": seasonal, "shared_source_limit": shared,
            "recourse_budget": variant["budget"]}


def bootstrap(kept: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """95% percentile interval of the fraction of kept years, resampling whole years."""

    draws = rng.integers(0, kept.size, size=(BOOTSTRAP, kept.size))
    fractions = kept[draws].mean(axis=1)
    low, high = np.percentile(fractions, [2.5, 97.5])
    return float(low), float(high)


def clopper_pearson(kept: int, years: int) -> tuple[float, float]:
    """Exact 95% interval of a binomial proportion."""

    low = 0.0 if kept == 0 else float(beta.ppf(0.025, kept, years - kept + 1))
    high = 1.0 if kept == years else float(beta.ppf(0.975, kept + 1, years - kept))
    return low, high


def headroom(model, label: str, instance, plan_rows, guarantees: dict) -> float:
    """The largest multiple of the guarantee vector the scenario delivers, plan fixed.

    common_level caps its level at 1; with weights scaled by the largest guarantee the cap sits
    where the most demanding claimant would be served in full, which no plan can exceed.
    """

    scale = 1.0 / max(guarantees.values())
    weights = {c: g * scale for c, g in guarantees.items()}
    return fixed.common_level(instance, label, plan_rows, weights) * scale


def not_below(left: list[float], right: list[float], tolerance: float = 1e-7) -> bool:
    """True if the sorted vector `left` is lexicographically at least `right`."""

    for a, b in zip(sorted(left), sorted(right)):
        if abs(a - b) > tolerance:
            return a > b
    return True


def main() -> None:
    started = time.perf_counter()
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    model = load_cti_benchmark(BENCHMARK)
    months = {p: int(p.split("-")[1]) for p in model.periods}
    days = {row["period_id"]: row["days"] for row in payload["periods"]}
    flows, gauge = read_gauge()
    index = dryness(flows, months, days)

    solution, plan_rows = fixed.published_plan(model)
    guarantees = dict(solution.guarantees)
    claimants = list(model.claimants)
    nominal = fixed.scenario_parameters(model, model.nominal_scenario)

    severe, severe_least, severe_overrun = fixed.operate(model, "severe", fixed.scenario_parameters(model, SEVERE), plan_rows)
    severe_pair = fixed.common_level(severe, "severe", plan_rows, {c: 1.0 for c in PARADISE_HIGHLINE})

    results: dict[str, dict] = {}
    for name, variant in VARIANTS.items():
        rows = {}
        for year in YEARS:
            ratios = index["years"][year]
            parameters = year_parameters(model, nominal, ratios, variant)
            instance, least, overrun = fixed.operate(model, "year", parameters, plan_rows, OVERRUN)
            shares, levels = fixed.leximin_levels(instance, "year", plan_rows, guarantees)
            row = {
                "least_effort": least,
                "effort_beyond_budget": overrun,
                "share_of_guarantee": shares,
                "promise_kept": {c: shares[c] >= 1 - KEPT and overrun <= OVERRUN for c in claimants},
                "levels": levels,
            }
            if name == PRIMARY:
                row["paradise_highline_common_service"] = fixed.common_level(
                    instance, "year", plan_rows, {c: 1.0 for c in PARADISE_HIGHLINE})
                row["headroom"] = headroom(model, "year", instance, plan_rows, guarantees)
            rows[year] = row
        results[name] = rows

    rng = np.random.default_rng(SEED)
    summaries = {}
    for name, rows in results.items():
        kept = {c: np.array([rows[y]["promise_kept"][c] for y in YEARS], dtype=float) for c in claimants}
        system = np.array([all(rows[y]["promise_kept"].values()) for y in YEARS], dtype=float)
        summaries[name] = {
            "reliability": {c: float(kept[c].mean()) for c in claimants},
            "reliability_95_percent_interval": {c: bootstrap(kept[c], rng) for c in claimants},
            "system_reliability": float(system.mean()),
            "system_reliability_95_percent_interval": bootstrap(system, rng),
            "years_a_promise_failed": {c: [y for y in YEARS if not rows[y]["promise_kept"][c]] for c in claimants},
            "mean_shortfall": {c: float(np.mean([1 - rows[y]["share_of_guarantee"][c] for y in YEARS])) for c in claimants},
            "largest_shortfall": {
                c: max(((1 - rows[y]["share_of_guarantee"][c], y) for y in YEARS), key=lambda item: item[0])
                for c in claimants},
            "years_beyond_budget": [y for y in YEARS if rows[y]["effort_beyond_budget"] > OVERRUN],
        }

    primary = results[PRIMARY]
    undisturbed = [y for y in YEARS if min(index["years"][y]["monthly_ratio"].values()) >= 1.0]
    pair = {y: primary[y]["paradise_highline_common_service"] for y in YEARS}
    checks = {
        "years_with_every_monthly_ratio_at_least_1": undisturbed,
        "those_years_keep_every_promise_within_budget": all(
            all(primary[y]["promise_kept"].values()) for y in undisturbed),
        "budget_0_40_not_below_0_25_in_every_year": all(
            not_below(list(results["budget 0.40"][y]["share_of_guarantee"].values()),
                      list(results["budget 0.25"][y]["share_of_guarantee"].values())) for y in YEARS),
        "unscaled_envelopes_not_below_scaled_in_every_year": all(
            not_below(list(results["envelopes unscaled"][y]["share_of_guarantee"].values()),
                      list(primary[y]["share_of_guarantee"].values())) for y in YEARS),
        "years_all_kept": {name: int(sum(all(rows[y]["promise_kept"].values()) for y in YEARS))
                           for name, rows in results.items()},
    }
    expectations = {
        "every_year_runs_within_budget_0_40": not summaries[PRIMARY]["years_beyond_budget"],
        "hyrum_more_reliable_than_highline":
            summaries[PRIMARY]["reliability"]["company_088"] > summaries[PRIMARY]["reliability"]["company_132"],
        "severe_paradise_highline_common_service": severe_pair,
        "severe_effort_beyond_budget": severe_overrun,
        "driest_year_for_paradise_highline": min(pair, key=pair.get),
        "lowest_year_paradise_highline_common_service": min(pair.values()),
        "severe_harsher_than_every_year": all(severe_pair < pair[y] - 1e-9 for y in YEARS),
        "years_not_harsher_than_severe": [y for y in YEARS if pair[y] <= severe_pair + 1e-9],
    }

    scenario_headroom = {}
    for scenario in model.scenarios:
        instance, _, overrun = fixed.operate(model, "scenario", fixed.scenario_parameters(model, scenario), plan_rows)
        scenario_headroom[scenario] = headroom(model, "scenario", instance, plan_rows, guarantees)
    year_headroom = {y: primary[y]["headroom"] for y in YEARS}
    added = {
        "note": "added after the first run; descriptive, no decision rule",
        "clopper_pearson_95_percent": {
            name: {**{c: clopper_pearson(int(sum(rows[y]["promise_kept"][c] for y in YEARS)), len(YEARS))
                      for c in claimants},
                   "system": clopper_pearson(int(sum(all(rows[y]["promise_kept"].values()) for y in YEARS)),
                                             len(YEARS))}
            for name, rows in results.items()},
        "headroom_by_scenario": scenario_headroom,
        "headroom_by_year": year_headroom,
        "smallest_headroom_year": min(year_headroom, key=year_headroom.get),
        "smallest_year_headroom": min(year_headroom.values()),
    }

    report = {
        "gauge": {**gauge, "site": "10105900", "name": "LITTLE BEAR RIVER AT PARADISE, UT",
                  "years": [YEARS[0], YEARS[-1]], "months": months,
                  "median_cfs_by_month": index["median_cfs_by_month"],
                  "median_season_cfs_days": index["median_season_cfs_days"]},
        "dryness": {y: index["years"][y] for y in YEARS},
        "published_guarantees": guarantees,
        "variants": VARIANTS,
        "primary": PRIMARY,
        "bootstrap": {"resamples": BOOTSTRAP, "seed": SEED, "unit": "year"},
        "years": {name: {str(y): rows[y] for y in YEARS} for name, rows in results.items()},
        "summary": summaries,
        "checks": checks,
        "expectations": expectations,
        "descriptive_added_after_the_first_run": added,
        "seconds": round(time.perf_counter() - started, 1),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    names = {c: row["claimant_name"] for c in claimants for row in payload["claimants"] if row["claimant_id"] == c}
    print(f"gauge 10105900, {YEARS[0]}-{YEARS[-1]}: monthly medians "
          f"{ {months[p]: round(v, 1) for p, v in zip(model.periods, index['median_cfs_by_month'].values())} } cfs")
    for name, summary in summaries.items():
        print(f"== {name}: every promise kept in {summary['system_reliability']:.1%} of the years "
              f"(95% {summary['system_reliability_95_percent_interval'][0]:.1%}-"
              f"{summary['system_reliability_95_percent_interval'][1]:.1%}); years beyond budget "
              f"{summary['years_beyond_budget'] or 'none'}")
        for c in claimants:
            low, high = summary["reliability_95_percent_interval"][c]
            shortfall, worst = summary["largest_shortfall"][c]
            print(f"   {c:12s} {names[c][:30]:30s} guarantee {guarantees[c]:.4f}  reliability "
                  f"{summary['reliability'][c]:6.1%} (95% {low:.1%}-{high:.1%})  largest shortfall "
                  f"{shortfall:.3f} ({worst})  failed {summary['years_a_promise_failed'][c] or 'never'}")
    print(f"checks: {checks}")
    print(f"severe vs the years, Paradise-Highline common service with the plan fixed: severe "
          f"{severe_pair:.4f}; lowest year {expectations['driest_year_for_paradise_highline']} "
          f"{expectations['lowest_year_paradise_highline_common_service']:.4f}; severe harsher than every "
          f"year: {expectations['severe_harsher_than_every_year']}")
    cp = added["clopper_pearson_95_percent"][PRIMARY]["system"]
    print(f"added after the first run: exact 95% interval of the system reliability {cp[0]:.1%}-{cp[1]:.1%}; "
          f"headroom (multiple of the guarantee vector delivered): scenarios "
          f"{ {s: round(v, 3) for s, v in scenario_headroom.items()} }; smallest year "
          f"{added['smallest_headroom_year']} {added['smallest_year_headroom']:.3f}")
    print(f"wrote {OUTPUT.relative_to(REPO)} in {report['seconds']} s")


if __name__ == "__main__":
    main()
