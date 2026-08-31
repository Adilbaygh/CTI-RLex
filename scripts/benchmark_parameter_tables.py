"""How much of each benchmark is observed, how much derived, how much assumed.

Appendix A describes the provenance of the parameters in words, which lets a reader follow
the reasoning but not weigh it: "where does this number come from?" is answered case by case
and never in aggregate, so nobody can say what fraction of the instance is data-informed. The
benchmarks already carry the answer -- every parameter row records the status of its own
value -- and this script counts it.

Counting requires one judgement, and it is made here in the open rather than buried: each
status string the generators write is mapped to observed, derived or assumed, and both the
raw string and the class are reported, so a reader who would classify a proxy differently can
see exactly which rows to move. Nothing else is interpreted.

The same pass extracts the coefficient tables the model defines but never displays: the
scenario weights and budgets, the control set with its normalizing volumes and effort
coefficients, and the shared source groups with their member coefficients and envelopes.
These are the numbers a reader needs to audit a recourse or group-envelope result, and they
exist only inside the released JSON until they are printed.

Run:  python scripts/benchmark_parameter_tables.py
Writes: results/benchmark_parameters.json
"""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
INSTANCES = {
    "little_bear_v2": REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    "cache_valley_v3": REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
}
OUTPUT = REPO / "results" / "benchmark_parameters.json"

# The one judgement this script makes, written down so it can be disagreed with. A value is
# observed when a source layer states it, derived when the build computes it from stated
# layers by a documented rule, and assumed when it comes from a modelling choice that no
# layer supports. A proxy is a derivation that the documentation already flags for
# calibration, so it is counted as derived and its own status string says the rest.
PROVENANCE = {
    "observed_design_attribute": "observed",
    # The claimant-terminal mapping is a spatial intersection of the service-area layer
    # with the network, not a value a layer states, so the rule above makes it derived --
    # which is what Appendix A.1 of the manuscript has always called it. The status string
    # itself is left alone: it sits in a checksummed CSV, and what it records is true and
    # narrower than its prefix suggests, that the claimant is resolved at company level
    # rather than at farmer level. It was never a statement about where the mapping
    # came from.
    "observed_company_level_not_farmer_level": "derived",
    "proxy_requires_calibration": "derived",
    "derived_requires_calibration": "derived",
    "derived_topology_repair": "derived",
    "derived_envelope_not_observed_2025_supply": "derived",
    "derived_operational_envelope_not_observed_hydrologic_supply": "derived",
    "derived_from_WRLU_method_with_assumed_method_efficiencies": "derived",
    "derived_attributes_plus_assumed_duty_and_profile": "derived",
    "assumed_exp_length_decay_0.005_per_km": "assumed",
    "assumed_exp_length_decay_0.001_per_km": "assumed",
    "lossless_logical_connector": "assumed",
    "experimental_normalization": "assumed",
    "experimental_derating": "assumed",
}

# Which field of which table carries the status of which parameter block. A block is a
# family of numbers a reader would ask one provenance question about.
BLOCKS = [
    ("Reach capacity", "edges", "capacity_status"),
    ("Reach efficiency", "edges", "efficiency_basis"),
    ("Source seasonal envelope", "sources", "limit_status"),
    ("Shared group envelope", "source_groups", "data_status"),
    ("Application efficiency", "terminal_parameters", "data_status"),
    ("Claimant-terminal mapping", "claimant_terminals", "mapping_status"),
    ("Monthly demand", "demands", "data_status"),
    ("Control normalization", "control_assets", "data_status"),
]


def classify(status: str) -> str:
    if status not in PROVENANCE:
        raise SystemExit(
            f"unclassified provenance status {status!r}; add it to PROVENANCE with a class, "
            "rather than letting it fall into a default that would hide it"
        )
    return PROVENANCE[status]


def provenance(benchmark: dict) -> dict[str, Any]:
    blocks = []
    totals: collections.Counter[str] = collections.Counter()
    for label, table, field in BLOCKS:
        rows = benchmark.get(table, [])
        if not rows:
            continue
        counts = collections.Counter(row[field] for row in rows)
        classes: collections.Counter[str] = collections.Counter()
        detail = []
        for status, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            provenance_class = classify(status)
            classes[provenance_class] += count
            detail.append({
                "status": status,
                "provenance": provenance_class,
                "rows": count,
                "share_percent": 100.0 * count / len(rows),
            })
        totals.update(classes)
        blocks.append({
            "block": label,
            "table": table,
            "field": field,
            "rows": len(rows),
            "by_provenance": dict(classes),
            "by_status": detail,
        })

    grand = sum(totals.values())
    return {
        "blocks": blocks,
        "rows_by_provenance": dict(totals),
        "share_by_provenance_percent": {
            key: 100.0 * value / grand for key, value in sorted(totals.items())
        },
        "total_rows": grand,
    }


def coefficient_tables(benchmark: dict) -> dict[str, Any]:
    members: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in benchmark["source_group_members"]:
        members[row["group_id"]].append({"source_id": row["source_id"], "beta": row["beta"]})

    controls = [
        {
            "control_asset_id": row["control_asset_id"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "control_label": row["control_label"],
            "reachable_claimants": row["reachable_claimants"],
            "normalization_scale_af": row["normalization_scale_af"],
            "effort_coefficient": row["effort_coefficient"],
            "basis": row["basis"],
        }
        for row in benchmark["control_assets"]
    ]
    connector_edges = {
        edge["edge_id"] for edge in benchmark["edges"]
        if edge["edge_role"] != "physical"
    }
    controlled = {row["resource_id"] for row in controls}
    return {
        "scenarios": [
            {
                "scenario_id": row["scenario_id"],
                "label": row["label"],
                "probability_weight": row["probability_weight"],
                "recourse_budget": row["recourse_budget"],
            }
            for row in benchmark["scenarios"]
        ],
        "controls": controls,
        "source_groups": [
            {
                "group_id": row["group_id"],
                "group_label": row["group_label"],
                "base_envelope_cfs": row["base_envelope_cfs"],
                "envelope_basis": row["envelope_basis"],
                "members": sorted(members[row["group_id"]], key=lambda item: item["source_id"]),
            }
            for row in benchmark["source_groups"]
        ],
        # The exclusion the recourse measure depends on: a logical connector repairs a gap in
        # the path table, so admitting one to the control set would make the reconfiguration
        # measure depend on how many database records represent one canal.
        "logical_connectors": len(connector_edges),
        "logical_connectors_in_the_control_set": sorted(connector_edges & controlled),
    }


def main() -> None:
    payload: dict[str, Any] = {"provenance_classes": PROVENANCE, "instances": {}}
    for name, path in INSTANCES.items():
        benchmark = json.loads(path.read_text(encoding="utf-8"))
        counted = provenance(benchmark)
        tables = coefficient_tables(benchmark)
        if tables["logical_connectors_in_the_control_set"]:
            raise SystemExit(
                f"{name}: a logical connector is in the control set, which the model forbids"
            )
        payload["instances"][name] = {
            "benchmark_id": benchmark["benchmark_id"],
            "provenance": counted,
            **tables,
        }

        print(f"{name}:")
        share = counted["share_by_provenance_percent"]
        print("  " + ", ".join(f"{key} {value:.1f}%" for key, value in sorted(share.items()))
              + f"  over {counted['total_rows']} parameter rows")
        for block in counted["blocks"]:
            classes = ", ".join(f"{key} {value}" for key, value in sorted(block["by_provenance"].items()))
            print(f"    {block['block']:<28} {block['rows']:>4} rows   {classes}")
        print(f"    {tables['logical_connectors']} logical connectors, "
              f"none in the control set of {len(tables['controls'])} assets")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
