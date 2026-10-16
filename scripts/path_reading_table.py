"""Produce results/path_reading_cache_valley.json: how the county paths are read.

The Utah Distribution Network lists, for every official path, the flowlines that serve one
water right. Twenty of the 51 county listings are not in flow order or name side branches,
and the benchmark reads every path as the set of reaches it lists (DATA/LittleBearRiver_2025_
Benchmark/generate_benchmark.py, LEXIMIN_PATH_READING). The generator records what that
reading changed in the validation report of the county benchmark; this script turns the
record into the table the Supplementary Material prints, using nothing but the released
benchmark:

  * for every path the reading changed: its water right and claimant, the reaches it lists
    and their length, the gap connectors kept, every connector of the sequential walk that
    is not built and why, and every connector that attaches the place of use, with the
    distance from the attachment node to the place-of-use node;
  * per claimant: how many of its paths changed and where its place of use is attached;
  * the range of the attachment distances over every terminal connector of the instance,
    so the changed attachments can be compared with the unchanged ones;
  * every run of listed reaches the reading does not build because it lies farther from the
    rest of its path than the rest spans: the path, its water right and claimant, the
    reaches, both distances and the distribution systems of the run and of the rest.

Distances are great-circle distances between the published node coordinates. They are
descriptive: a place-of-use node marks a service area, not a turnout, and a connector is
lossless and of zero length whatever the distance.

Run:  python scripts/path_reading_table.py
Writes: results/path_reading_cache_valley.json
"""

from __future__ import annotations

import collections
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIRECTORY = REPO / "DATA" / "CacheValley_2025_Benchmark"
OUTPUT = REPO / "results" / "path_reading_cache_valley.json"
EARTH_RADIUS_KM = 6371.0088

REASONS = {
    "jumps_back_upstream_to_another_listed_branch": "returns upstream to start another listed branch",
    "jumps_over_reaches_listed_later": "skips over reaches the listing names later",
}


def distance_km(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(
        math.radians, (float(a["latitude"]), float(a["longitude"]), float(b["latitude"]), float(b["longitude"]))
    )
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def main() -> None:
    payload = json.loads((DIRECTORY / "benchmark.json").read_text(encoding="utf-8"))
    report = json.loads((DIRECTORY / "validation_report.json").read_text(encoding="utf-8"))
    record = report.get("path_reading", {})
    if not record.get("paths"):
        raise SystemExit("the county benchmark records no path read as a set; was it built with the set reading?")

    nodes = {row["node_id"]: row for row in payload["nodes"]}
    edges = {row["edge_id"]: row for row in payload["edges"]}
    paths = {row["path_id"]: row for row in payload["paths"]}
    claimant_of_node = {row["terminal_node"]: row["claimant_id"] for row in payload["claimant_terminals"]}
    names = {row["claimant_id"]: row["claimant_name"] for row in payload["claimants"]}

    def attachment(connector: str) -> dict:
        edge = edges[connector]
        return {
            "connector": connector,
            "attachment_node": edge["from_node"],
            "distance_to_place_of_use_km": round(distance_km(nodes[edge["from_node"]], nodes[edge["to_node"]]), 3),
        }

    rows = []
    for path_id in sorted(record["paths"], key=lambda item: int(item[2:])):
        entry = record["paths"][path_id]
        path = paths[path_id]
        listed = entry["listed_reaches"]
        terminal_connectors = [attachment(connector) for connector in entry["terminal_connectors"]]
        rows.append(
            {
                "path_id": path_id,
                "water_right_number": path["water_right_number"],
                "claimant_id": claimant_of_node[path["terminal_node"]],
                "claimant_name": names[claimant_of_node[path["terminal_node"]]],
                "source_id": path["source_id"],
                "terminal_node": path["terminal_node"],
                "listed_reaches": len(listed),
                "listed_km": round(sum(float(edges[reach]["length_m"]) for reach in listed) / 1000.0, 3),
                "gap_connectors_kept": entry["gap_connectors_kept"],
                "walk_connectors_not_built": {
                    connector: REASONS[reason] for connector, reason in entry["walk_connectors_not_built"].items()
                },
                "sequential_reading_terminal_connector": entry["walk_terminal_connector"],
                "terminal_connectors": terminal_connectors,
                "listed_reaches_not_reachable_from_the_diversion": entry[
                    "listed_reaches_not_reachable_from_the_diversion"
                ],
            }
        )

    by_claimant: dict[str, dict] = {}
    for row in rows:
        summary = by_claimant.setdefault(
            row["claimant_id"],
            {"claimant_name": row["claimant_name"], "paths_read_as_sets": [], "terminal_connectors": {}},
        )
        summary["paths_read_as_sets"].append(row["path_id"])
        for item in row["terminal_connectors"]:
            summary["terminal_connectors"][item["connector"]] = item["distance_to_place_of_use_km"]

    every_terminal_connector = [
        attachment(row["edge_id"])
        for row in payload["edges"]
        if row["edge_role"] == "derived_connector" and row["to_node"] in claimant_of_node
    ]
    changed_connectors = {item["connector"] for row in rows for item in row["terminal_connectors"]}
    not_built = collections.Counter(
        reason for row in rows for reason in row["walk_connectors_not_built"].values()
    )
    distinct_not_built = sorted({connector for row in rows for connector in row["walk_connectors_not_built"]})
    reaches_not_built = [
        {
            "path_id": path_id,
            "water_right_number": paths[path_id]["water_right_number"],
            "claimant_id": claimant_of_node[paths[path_id]["terminal_node"]],
            **run,
        }
        for path_id, runs in sorted(
            record.get("listed_reaches_not_built", {}).items(), key=lambda item: int(item[0][2:])
        )
        for run in runs
    ]

    output = {
        "benchmark_id": payload["benchmark_id"],
        "rule": record["rule"],
        "paths": len(payload["paths"]),
        "paths_read_as_sets": len(rows),
        "claimants_affected": len(by_claimant),
        "walk_connectors_not_built": len(distinct_not_built),
        "walk_connectors_not_built_by_reason_and_path": dict(sorted(not_built.items())),
        "gap_connectors_kept_on_changed_paths": sorted({c for row in rows for c in row["gap_connectors_kept"]}),
        "listed_reaches_not_reachable_from_their_diversion": sorted(
            {reach for row in rows for reach in row["listed_reaches_not_reachable_from_the_diversion"]}
        ),
        "attachment_distance_km": {
            "every_terminal_connector": [
                min(item["distance_to_place_of_use_km"] for item in every_terminal_connector),
                max(item["distance_to_place_of_use_km"] for item in every_terminal_connector),
            ],
            "terminal_connectors_of_changed_paths": [
                min(item["distance_to_place_of_use_km"] for item in every_terminal_connector if item["connector"] in changed_connectors),
                max(item["distance_to_place_of_use_km"] for item in every_terminal_connector if item["connector"] in changed_connectors),
            ],
        },
        "by_claimant": dict(sorted(by_claimant.items())),
        "rows": rows,
        "listed_reaches_not_built": reaches_not_built,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    print(f"{output['paths_read_as_sets']} of {output['paths']} paths read as sets, "
          f"{output['claimants_affected']} claimants affected")
    print(f"walk connectors not built: {output['walk_connectors_not_built']} distinct; "
          + ", ".join(f"{count} x {reason}" for reason, count in output["walk_connectors_not_built_by_reason_and_path"].items()))
    print(f"attachment distance, every terminal connector: {output['attachment_distance_km']['every_terminal_connector']} km; "
          f"changed paths: {output['attachment_distance_km']['terminal_connectors_of_changed_paths']} km")
    for claimant, summary in output["by_claimant"].items():
        print(f"  {claimant:14s} {summary['claimant_name'][:40]:40s} {len(summary['paths_read_as_sets']):2d} path(s); "
              + ", ".join(f"{c} {d:.2f} km" for c, d in summary["terminal_connectors"].items()))
    for run in reaches_not_built:
        print(f"not built on {run['path_id']} ({run['water_right_number']}): {', '.join(run['reaches'])} "
              f"({'; '.join(run['flowline_names'])}, systems {run['system_ids']}), "
              f"{run['distance_to_the_rest_of_the_path_km']} km from the rest of the path, "
              f"which spans {run['span_of_the_rest_of_the_path_km']} km (systems {run['system_ids_of_the_rest_of_the_path']})")
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
