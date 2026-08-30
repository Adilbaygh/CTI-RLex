"""What the county instance leaves out, and how much water it represents.

Sixteen Cache Valley irrigation-company service areas own an official delivery terminal in
the Utah Water Right Distribution Network. Ten of them are claimants of the published
benchmark. The released package reported the six exclusions by name and reason, which
answers "who" but not "how much": a reader could not tell whether the instance omits six
marginal parcels or a third of the valley's irrigated demand, and that is the difference
between a scoping decision and a bias.

This script closes that gap from the same open layers the benchmark is built from. For
every one of the sixteen it reports the irrigated non-fallow WRLU acreage assigned to the
service polygon and the seasonal net demand that acreage implies under the benchmark's own
duty assumption, and for each excluded area the routes it lost and the connector rejection
that removed them. The excluded share of demand is then a number rather than an impression.

Two exclusion rules are distinguished, because they are not the same kind of fact:

    no irrigated acres     the service polygon receives no irrigated non-fallow parcel, so
                           the area carries no demand and no service ratio to be fair about
    no acyclic route       the area has demand, but the acyclicity repair rejected the
                           connectors its every route depended on

Only the second is a limitation of the method's instance; the first is an empty claimant.

Run:  python scripts/excluded_service_areas.py     (needs LEXIMIN_DATASETS)
Writes: results/excluded_service_areas.json
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO / "DATA" / "LittleBearRiver_2025_Benchmark"
PUBLISHED = REPO / "DATA" / "CacheValley_2025_Benchmark"
OUTPUT = REPO / "results" / "excluded_service_areas.json"

sys.path.insert(0, str(BENCHMARK_DIR))


def demand_acres_by_claimant(companies: dict) -> dict[str, float]:
    """Irrigated non-fallow WRLU acreage assigned to each service polygon.

    This is the quantity the selection filter already computes; it is recomputed here for
    all sixteen companies rather than only the survivors, so the excluded areas can be
    reported with the same measure as the retained ones.
    """

    import generate_benchmark as gb

    gb.COMPANIES = companies
    parcels = gb.extract_parcels(gb.extract_service_areas())
    acres: dict[str, float] = collections.defaultdict(float)
    for parcel in parcels:
        if gb.is_irrigated_demand_parcel(parcel):
            acres[parcel["claimant_id"]] += float(parcel["acres"])
    return dict(acres)


def main() -> None:
    import generate_benchmark as gb

    selection = json.loads((PUBLISHED / "selection.json").read_text(encoding="utf-8"))
    summary = json.loads((PUBLISHED / "discovery_summary.json").read_text(encoding="utf-8"))
    reduction = summary["acyclic_reduction"]
    companies = selection["companies"]

    acres = demand_acres_by_claimant(companies)
    duty = gb.DEMAND_DUTY_AF_PER_ACRE

    # Which connector rejection removed which route, grouped by the terminal it served.
    dropped: dict[str, dict] = collections.defaultdict(
        lambda: {"path_ids": [], "blocking_connectors": set()}
    )
    for row in reduction["paths_dropped"]:
        entry = dropped[row["terminal_node"]]
        entry["path_ids"].append(row["path_id"])
        entry["blocking_connectors"].update(row["blocking_connectors"].split("|"))

    rejection_reason = {
        row["connector"]: row["reason"] for row in reduction["connectors_rejected"]
    }
    routed = set(summary["claimants"])
    no_acres = {
        item.split(" ", 1)[0] for item in summary["excluded_no_irrigated_acres"]
    }

    rows = []
    for key, specification in sorted(companies.items(), key=lambda item: int(item[0])):
        claimant = specification["claimant_id"]
        terminal = f"n_{specification['terminal_raw']}"
        lost = dropped.get(terminal, {"path_ids": [], "blocking_connectors": set()})
        if key in routed:
            status = "claimant"
        elif claimant in no_acres:
            status = "excluded_no_irrigated_acres"
        else:
            status = "excluded_no_acyclic_route"
        rows.append(
            {
                "claimant_id": claimant,
                "name": specification["name"],
                "terminal_node": terminal,
                "status": status,
                "irrigated_demand_acres": round(acres.get(claimant, 0.0), 3),
                "seasonal_net_demand_af": round(acres.get(claimant, 0.0) * duty, 3),
                "paths_dropped": len(lost["path_ids"]),
                "dropped_path_ids": sorted(lost["path_ids"]),
                "blocking_connectors": [
                    {"connector": connector, "reason": rejection_reason.get(connector, "")}
                    for connector in sorted(lost["blocking_connectors"])
                ],
            }
        )

    def total(status: str) -> float:
        return sum(row["seasonal_net_demand_af"] for row in rows if row["status"] == status)

    claimant_demand = total("claimant")
    excluded_demand = total("excluded_no_acyclic_route")
    qualifying = claimant_demand + excluded_demand

    payload = {
        "instance": "cache_valley_2025_multiclaimant_v3",
        "demand_duty_af_per_acre": duty,
        "demand_basis": "irrigated_nonfallow_WRLU_acres_x_assumed_net_duty",
        "service_areas_with_official_terminal": len(rows),
        "claimants": sum(1 for row in rows if row["status"] == "claimant"),
        "excluded_no_irrigated_acres": sum(
            1 for row in rows if row["status"] == "excluded_no_irrigated_acres"
        ),
        "excluded_no_acyclic_route": sum(
            1 for row in rows if row["status"] == "excluded_no_acyclic_route"
        ),
        "claimant_seasonal_demand_af": round(claimant_demand, 3),
        "excluded_seasonal_demand_af": round(excluded_demand, 3),
        "excluded_share_of_qualifying_demand_percent": (
            round(100.0 * excluded_demand / qualifying, 2) if qualifying else 0.0
        ),
        "logical_connector_parameterization": {
            "capacity_cfs_base": "minimum_adjacent_path_capacity",
            "efficiency_base": 1.0,
            "efficiency_basis": "lossless_logical_connector",
            "length_m": 0.0,
            "capacity_status": "derived_topology_repair",
            "note": (
                "a logical connector carries no loss and no length: it stands for a gap in "
                "the path table, not for a reach, so giving it a loss would invent physical "
                "conveyance that the layers do not record"
            ),
        },
        "service_areas": rows,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"{payload['service_areas_with_official_terminal']} service areas with a terminal")
    print(f"  claimants                  : {payload['claimants']:>2}"
          f"   {claimant_demand:>10.1f} af")
    print(f"  excluded, no irrigated acres: {payload['excluded_no_irrigated_acres']:>2}")
    print(f"  excluded, no acyclic route : {payload['excluded_no_acyclic_route']:>2}"
          f"   {excluded_demand:>10.1f} af"
          f"   ({payload['excluded_share_of_qualifying_demand_percent']}% of qualifying demand)")
    print()
    for row in rows:
        if row["status"] == "excluded_no_acyclic_route":
            blockers = ", ".join(item["connector"] for item in row["blocking_connectors"])
            print(f"  {row['claimant_id']}  {row['name'][:42]:<42} "
                  f"{row['seasonal_net_demand_af']:>9.1f} af  "
                  f"{row['paths_dropped']} route(s) lost to {blockers}")
    print(f"\nwrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
