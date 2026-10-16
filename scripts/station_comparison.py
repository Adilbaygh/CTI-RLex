"""Set the three-claimant benchmark against the canal flows measured in 2025 (Reviewer 1, point 2.2).

A reviewer asked how the benchmark's flows compare with what the canals actually carried.
The Little Bear River benchmark names five measuring stations of the Utah Division of Water
Rights on the canals of its three claimants: the benchmark's measurement_stations table links
each to a reach, and each claimant's station identifiers come from the service-area layer.
Their River Commissioner records for 2025 -- mean daily discharge in cubic feet per second --
and the viewer's monthly summary of each station's whole record are kept, with their
provenance, in DATA/LittleBearRiver_2025_Observations. The benchmark does not read them.

Observed. For each station and each period of the benchmark (May to September 2025), the volume
of the days that carry a record (1 cfs-day = 1.98347 acre-feet) and the share of the month's days
they cover. Where at least 90% of the days carry a record, the month's volume is the mean of the
recorded days times the days of the month; a month with less coverage is reported but not tested.
Each recorded-day volume is checked against the viewer's own monthly summary for 2025, and the
station's earlier years give the range of the same month in its record.

Modelled, in the nominal scenario of the CTI-RLex solution:

  * the requirement: the claimant's net demand divided by its application efficiency, the gross
    volume that serves its place of use in full; at a station it is carried back up the canal by
    dividing by the efficiency of every reach from the station's reach to the place of use;
  * the plan: the flow on the station's reach in the reported plan, and its range over the
    optimal face (scripts/flow_uniqueness.py);
  * for each claimant, its gross withdrawal at the place of use, reported and over the face,
    against the sum of its canals. Stations on the same reach measure the same flow and are
    reported side by side, never added.

Hypothesis H-2.2 (requirements/hypotheses.md), written before the records were read: in most
months the observed volume is within a factor of two of the model's nominal flow, and the
observed seasonal peak falls in June to August. A station is compared at its reach where the
plan carries the claimant's water through that reach in some month; where the plan carries none
there -- Hyrum is served from Hyrum Reservoir through the Hyrum Feeder Canal, not down the Hyrum
Canal -- the claimant's total diversion is compared with its withdrawal instead. The ratio to
the requirement is reported beside it, so that the demand side and the allocation can be told
apart. "Most months" means more than half of the tested months.

Also reported for each station: the largest daily discharge, and the days on which the discharge
exceeded the design capacity the benchmark gives the station's reach.

Run:  python scripts/station_comparison.py
Writes: results/station_comparison.json
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import flow_uniqueness as faces  # noqa: E402
from leximin.dag import load_cti_benchmark, solve_cti_rlex  # noqa: E402

BENCHMARK = REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"
OBSERVED = REPO / "DATA" / "LittleBearRiver_2025_Observations"
OUTPUT = REPO / "results" / "station_comparison.json"

YEAR = 2025
CFS_DAY_TO_AF = 1.9834710743801653  # the benchmark generator's conversion
COVERAGE = 0.9                       # share of a month's days that must carry a record to test it
FACTOR = 2.0                         # H-2.2: within a factor of two
PEAK_MONTHS = (6, 7, 8)              # H-2.2: the observed peak falls in June to August
SUMMARY_CHECK_AF = 0.5               # the viewer rounds its monthly summary to whole acre-feet
NO_FLOW_AF = 1e-6                    # a plan flow below this carries no water
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


# --------------------------------------------------------------------------------------
# Observations


def read_daily(path: Path) -> tuple[dict[str, str], dict[dt.date, float]]:
    """The viewer's daily comma-delimited file: a header block, then Date,Flow rows."""

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("Date,"))
    header = dict(line.split(",", 1) for line in lines[:start] if "," in line)
    values: dict[dt.date, float] = {}
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        day, flow = line.split(",")[:2]
        date = dt.datetime.strptime(day, "%m/%d/%Y").date()
        if date in values:
            raise ValueError(f"{path.name}: two records for {date}")
        values[date] = float(flow)
    return header, values


def read_monthly_summary(path: Path) -> dict[int, dict[int, float]]:
    """The viewer's monthly summary: one row per year, a right-aligned column per month."""

    lines = path.read_text(encoding="ascii").splitlines()
    header = next(line for line in lines if line.strip().startswith("YEAR"))
    ends = {month: header.index(label) + len(label) for month, label in enumerate(MONTHS, start=1)}
    table: dict[int, dict[int, float]] = {}
    for line in lines:
        match = re.match(r"^\s+(\d{4})\s", line)
        if not match:
            continue
        row = {}
        for month, end in ends.items():
            cell = line[end - 9:end].strip() if len(line) >= end - 8 else ""
            if cell:
                row[month] = float(cell.rstrip("."))
        table[int(match.group(1))] = row
    return table


def month_record(daily: dict[dt.date, float], month: int) -> dict:
    days = calendar.monthrange(YEAR, month)[1]
    recorded = [value for date, value in daily.items() if date.year == YEAR and date.month == month]
    volume = sum(recorded) * CFS_DAY_TO_AF
    coverage = len(recorded) / days
    return {
        "days": days,
        "days_recorded": len(recorded),
        "coverage": round(coverage, 4),
        "recorded_volume_af": volume,
        "volume_af": volume * days / len(recorded) if coverage >= COVERAGE else None,
        "tested": coverage >= COVERAGE,
    }


def history(summary: dict[int, dict[int, float]], month: int) -> dict:
    """The same month in the station's earlier years, as the viewer sums them."""

    earlier = sorted(row[month] for year, row in summary.items() if year < YEAR and month in row)
    if not earlier:
        return {"years": 0}
    this = summary.get(YEAR, {}).get(month)
    return {
        "years": len(earlier),
        "first_year": min(year for year, row in summary.items() if year < YEAR and month in row),
        "minimum_af": earlier[0],
        "median_af": statistics.median(earlier),
        "mean_af": statistics.fmean(earlier),
        "maximum_af": earlier[-1],
        "share_of_earlier_years_below_2025": None if this is None else sum(value < this for value in earlier) / len(earlier),
    }


# --------------------------------------------------------------------------------------
# Model


def efficiency_to_place_of_use(payload: dict, model, edge: str, terminal_node: str, period: str) -> float:
    """Product of the reach efficiencies from ``edge`` down to the place of use, on every
    official path of the claimant that uses ``edge``; the paths must agree."""

    nominal = model.nominal_scenario
    by_path: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in payload["path_edges"]:
        if row["terminal_node"] == terminal_node:
            by_path[row["path_id"]].append((int(row["sequence"]), row["edge_id"]))
    products = set()
    for steps in by_path.values():
        sequence = [identifier for _, identifier in sorted(steps)]
        if edge not in sequence:
            continue
        product = 1.0
        for identifier in sequence[sequence.index(edge):]:
            product *= model.edge_efficiency[nominal, period, identifier]
        products.add(round(product, 12))
    if len(products) != 1:
        raise ValueError(f"{edge}: the paths to {terminal_node} give efficiencies {sorted(products)}")
    return products.pop()


def ratio(observed: float | None, modelled: float) -> float | None:
    if observed is None or modelled <= NO_FLOW_AF:
        return None
    return observed / modelled


def within(value: float | None) -> bool:
    return value is not None and 1.0 / FACTOR <= value <= FACTOR


def main() -> None:
    started = time.perf_counter()
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    provenance = json.loads((OBSERVED / "provenance.json").read_text(encoding="utf-8"))
    model = load_cti_benchmark(BENCHMARK)
    solution = solve_cti_rlex(model)
    face = faces.Face(model, solution.guarantees, faces.preserved_rows(model, solution))
    nominal = model.nominal_scenario
    periods = list(model.periods)
    month_of = {period: int(period.split("-")[1]) for period in periods}
    if any(not period.startswith(f"{YEAR}-") for period in periods):
        raise ValueError(f"the benchmark periods are not all in {YEAR}: {periods}")

    names = {row["claimant_id"]: row["claimant_name"] for row in payload["claimants"]}
    claimant_of = {
        station.strip(): row["claimant_id"]
        for row in payload["claimants"]
        for station in row["measurement_station_ids"].split(",")
        if station.strip()
    }
    capacity_cfs = {row["edge_id"]: float(row["capacity_cfs_base"]) for row in payload["edges"]}
    terminal_of = {}
    for claimant in model.claimants:
        terminals = model.terminals_by_claimant[claimant]
        if len(terminals) != 1:
            raise ValueError(f"{claimant} has {len(terminals)} places of use; the comparison assumes one")
        terminal_of[claimant] = terminals[0]

    def requirement(claimant: str, period: str) -> float:
        terminal = terminal_of[claimant]
        return model.demand[period, claimant] / model.application_efficiency[period, terminal.terminal_id]

    def withdrawal(claimant: str, period: str) -> tuple[float, float, float]:
        key = ("w", nominal, period, terminal_of[claimant].terminal_id)
        low, high = face.extremes({key: 1.0})
        return solution.gross_terminal_withdrawal[nominal, period, key[3]], low, high

    # ---------------------------------------------------------------- stations
    stations: dict[str, dict] = {}
    for record in payload["measurement_stations"]:
        station = str(record["station_id"])
        details = provenance["stations"][station]
        header, daily = read_daily(OBSERVED / details["file"])
        summary = read_monthly_summary(OBSERVED / f"monthly-summary-{station}.txt")
        claimant = claimant_of[station]
        edge = record["linked_edge_id"] or None
        months = {}
        for period in periods:
            month = month_of[period]
            row = month_record(daily, month)
            viewer = summary.get(YEAR, {}).get(month)
            row["viewer_monthly_summary_af"] = viewer
            row["agrees_with_viewer_summary"] = (
                viewer is None and row["days_recorded"] == 0
                or viewer is not None and abs(row["recorded_volume_af"] - viewer) <= SUMMARY_CHECK_AF
            )
            row["earlier_years"] = history(summary, month)
            required = requirement(claimant, period)
            row["claimant_requirement_at_place_of_use_af"] = required
            if edge is not None:
                efficiency = efficiency_to_place_of_use(payload, model, edge, terminal_of[claimant].node, period)
                at_station = required / efficiency
                low, high = face.extremes({("q", nominal, period, edge): 1.0})
                plan = solution.edge_flow[nominal, period, edge]
                observed = row["volume_af"]
                row.update({
                    "efficiency_station_to_place_of_use": efficiency,
                    "requirement_at_station_af": at_station,
                    "plan_flow_af": plan,
                    "plan_flow_range_af": [low, high],
                    "ratio_to_requirement": ratio(observed, at_station),
                    "ratio_to_plan": ratio(observed, plan),
                    "some_optimal_plan_within_factor": (
                        None if observed is None else (high >= observed / FACTOR and low <= observed * FACTOR)
                    ),
                })
            months[period] = row
        season = [value for date, value in daily.items() if date.year == YEAR and month_of.get(f"{YEAR}-{date.month:02d}")]
        largest = max(season) if season else None
        stations[station] = {
            "station_name": header.get("StationName", details["station_name"]),
            "units": header.get("Units", ""),
            "claimant_id": claimant,
            "linked_edge_id": edge,
            "measuring_device": details["measuring_device"],
            "record_rating": details["record_rating"],
            "months": months,
            "season_largest_daily_cfs": largest,
            "reach_design_capacity_cfs": capacity_cfs.get(edge) if edge else None,
            "season_days_above_design_capacity": (
                sum(value > capacity_cfs[edge] for value in season) if edge else None
            ),
            "plan_carries_water_through_the_reach": (
                any(solution.edge_flow[nominal, period, edge] > NO_FLOW_AF for period in periods) if edge else None
            ),
        }

    # ---------------------------------------------------------------- claimants
    claimants: dict[str, dict] = {}
    for claimant in model.claimants:
        own = sorted(station for station, owner in claimant_of.items() if owner == claimant and station in stations)
        # Stations on one reach measure one flow: each is an alternative, never a summand.
        groups: dict[str, list[str]] = defaultdict(list)
        for station in own:
            groups[stations[station]["linked_edge_id"] or f"unlinked:{station}"].append(station)
        alternatives = [[]]
        for members in groups.values():
            alternatives = [chosen + [member] for chosen in alternatives for member in members]
        months = {}
        for period in periods:
            plan, low, high = withdrawal(claimant, period)
            required = requirement(claimant, period)
            totals = []
            for chosen in alternatives:
                rows = [stations[station]["months"][period] for station in chosen]
                observed = (
                    sum(row["volume_af"] for row in rows) if all(row["tested"] for row in rows) else None
                )
                totals.append({
                    "stations": chosen,
                    "observed_af": observed,
                    "ratio_to_requirement": ratio(observed, required),
                    "ratio_to_plan_withdrawal": ratio(observed, plan),
                })
            months[period] = {
                "requirement_af": required,
                "plan_withdrawal_af": plan,
                "plan_withdrawal_range_af": [low, high],
                "observed": totals,
            }
        claimants[claimant] = {"claimant_name": names[claimant], "stations": own, "months": months}

    # ---------------------------------------------------------------- H-2.2
    verdicts = {}
    for claimant, entry in claimants.items():
        for station in entry["stations"]:
            item = stations[station]
            if item["linked_edge_id"] is None:
                continue
            at_reach = bool(item["plan_carries_water_through_the_reach"])
            tested = [period for period in periods if item["months"][period]["tested"]]
            if at_reach:
                plan_ratios = {period: item["months"][period]["ratio_to_plan"] for period in tested}
                requirement_ratios = {period: item["months"][period]["ratio_to_requirement"] for period in tested}
                level = "reach"
            else:
                choice = next(
                    total for total in entry["months"][periods[0]]["observed"] if station in total["stations"]
                )["stations"]
                rows = {
                    period: next(total for total in entry["months"][period]["observed"] if total["stations"] == choice)
                    for period in periods
                }
                tested = [period for period in periods if rows[period]["observed_af"] is not None]
                plan_ratios = {period: rows[period]["ratio_to_plan_withdrawal"] for period in tested}
                requirement_ratios = {period: rows[period]["ratio_to_requirement"] for period in tested}
                level = "claimant total (" + " + ".join(choice) + ")"
            volumes = (
                {period: item["months"][period]["volume_af"] for period in tested}
                if at_reach
                else {period: rows[period]["observed_af"] for period in tested}
            )
            peak = max(volumes, key=volumes.get) if volumes else None
            within_plan = sum(within(value) for value in plan_ratios.values())
            within_requirement = sum(within(value) for value in requirement_ratios.values())
            verdicts[station] = {
                "claimant_id": claimant,
                "compared_at": level,
                "tested_months": tested,
                "ratio_to_plan": plan_ratios,
                "ratio_to_requirement": requirement_ratios,
                "months_within_factor_of_plan": within_plan,
                "months_within_factor_of_requirement": within_requirement,
                "observed_peak_month": peak,
                "peak_in_june_to_august": peak is not None and month_of[peak] in PEAK_MONTHS,
                "consistent_with_plan": within_plan * 2 > len(tested),
                "consistent_with_requirement": within_requirement * 2 > len(tested),
            }

    output = {
        "benchmark_id": payload["benchmark_id"],
        "observations": {key: provenance[key] for key in ("dataset", "publisher", "source", "retrieved", "record_status")},
        "constants": {
            "cfs_day_to_af": CFS_DAY_TO_AF,
            "coverage_needed_to_test_a_month": COVERAGE,
            "factor": FACTOR,
            "peak_months": list(PEAK_MONTHS),
        },
        "every_2025_month_agrees_with_the_viewer_summary": all(
            row["agrees_with_viewer_summary"] for item in stations.values() for row in item["months"].values()
        ),
        "stations": stations,
        "claimants": claimants,
        "hypothesis_H_2_2": verdicts,
        "seconds": round(time.perf_counter() - started, 1),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    print(f"every 2025 month agrees with the viewer's monthly summary: "
          f"{output['every_2025_month_agrees_with_the_viewer_summary']}")
    for station, item in stations.items():
        print(f"{station} {item['station_name']:34s} reach {item['linked_edge_id'] or '-':8s} "
              f"largest {item['season_largest_daily_cfs'] or 0:6.2f} cfs, design "
              f"{item['reach_design_capacity_cfs'] or 0:5.1f} cfs, days above: {item['season_days_above_design_capacity']}")
        for period, row in item["months"].items():
            observed = row["volume_af"]
            text = (f"   {period}: observed {row['recorded_volume_af']:7.1f} af over {row['days_recorded']:2d}/{row['days']} days"
                    + (f" -> {observed:7.1f}" if observed is not None else " (not tested)"))
            if "plan_flow_af" in row:
                low, high = row["plan_flow_range_af"]
                text += (f"; requirement at station {row['requirement_at_station_af']:7.1f}, plan {row['plan_flow_af']:7.1f}"
                         f" [{low:7.1f}, {high:7.1f}]")
            print(text)
    for station, verdict in verdicts.items():
        print(f"H-2.2 {station} at {verdict['compared_at']}: within x{FACTOR:g} of the plan in "
              f"{verdict['months_within_factor_of_plan']}/{len(verdict['tested_months'])} months, of the requirement in "
              f"{verdict['months_within_factor_of_requirement']}/{len(verdict['tested_months'])}; peak {verdict['observed_peak_month']} "
              f"(June-August: {verdict['peak_in_june_to_august']})")
    print(f"wrote {OUTPUT.relative_to(REPO)} in {output['seconds']} s")


if __name__ == "__main__":
    main()
