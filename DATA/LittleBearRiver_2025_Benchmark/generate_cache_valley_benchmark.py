"""Build the Cache Valley 2025 multi-claimant CTI-RLex benchmark.

This driver reuses every extraction, derivation and provenance routine of
``generate_benchmark.py``. It differs only in *selection*: instead of three hand-picked
irrigation companies it takes, from the same open Utah layers, every Cache Valley
irrigation-company service area that owns an official delivery terminal in the Utah Water
Right Distribution Network.

Reconstruction note. The source of this driver was lost; only a Python 3.10 ``.pyc`` of an
earlier version survived. That version is demonstrably older than the released benchmark: it
names the reference scenario ``reference``, gives it a non-zero recourse budget, derates the
shared envelopes by different factors, and promotes no head gates to recourse controls. This
file is rebuilt from that bytecode, and every place where the two disagree is decided by the
released records rather than by the bytecode -- the reconstruction is checked the only way a
reconstruction can be, by reproducing the published selection, reduction, derating and
benchmark records exactly.

That includes the discovery pass: ``discover`` selects the claimants, terminals and paths
from the raw Utah layers with its own point-in-polygon test and no geospatial dependency, so
``selection.json`` is a cache and not an input -- delete it and the pass runs again and must
write the same bytes back.

Construction takes two passes. The acyclicity repair can leave a service area with no route
at all, and which areas those are is known only after the repair has run -- but the shared
source groups are derived from the claimant set, so they must be derived from the survivors.
Pass one therefore stops as soon as the repair reports them; pass two rebuilds with the
survivors as claimants while keeping pass one's path set, so the repair sees the same
candidate connectors and reaches the same graph. ``scripts/rebuild_cache_valley.py`` drives
both, and passes the survivor list between them through ``unrouted_claimants.json``.

Run with ``LEXIMIN_DATASETS`` pointing at the open-data root.
"""

from __future__ import annotations

import collections
import gc
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import generate_benchmark as gb  # noqa: E402

TARGET = HERE.parent / "CacheValley_2025_Benchmark"
COUNTY = "Cache"
SELECTION = TARGET / "selection.json"
UNROUTED = TARGET / "unrouted_claimants.json"
BENCHMARK_ID = "cache_valley_2025_multiclaimant_v3"

# The keys a cached selection must carry before it can be reused.
REQUIRED = {"companies", "selected_paths", "terminal_to_company", "source_to_company", "path_terminal"}

# Physical head gates promoted to recourse control assets alongside the sources: for each
# claimant terminal node the last physical reach before the derived terminal connector.
# The list is recovered from ``control_assets`` in the released benchmark, in the released
# order; it cannot be derived here, because the reduced graph that identifies each head gate
# only exists inside the build. The surviving bytecode promotes no edges at all, which is
# the single largest reason a build from it is smaller than the published program.
EXTRA_CONTROL_EDGES = [
    ("e_8949", "Head gate at n_16800"),
    ("e_5868", "Head gate at n_16801"),
    ("e_15158", "Head gate at n_16802"),
    ("e_13081", "Head gate at n_16803"),
    ("e_9834", "Head gate at n_16804"),
    ("e_9121", "Head gate at n_16816"),
    ("e_9861", "Head gate at n_16817"),
    ("e_8851", "Head gate at n_16823"),
    ("e_8842", "Head gate at n_16824"),
    ("e_8940", "Head gate at n_16827"),
]

# The same head gates, indexed by the terminal node each one feeds.
HEAD_GATES = {label.rsplit(" ", 1)[-1]: edge_id for edge_id, label in EXTRA_CONTROL_EDGES}

# A restricted subsystem is throttled on its reaches as well as on its shared envelope: the
# head gates of its own terminals carry this capacity factor, the level the Little Bear
# canal-restriction scenario also uses. Everything else stays at 1.0.
RESTRICTED_HEAD_GATE_FACTOR = 0.35

# In a subsystem-restriction scenario one diversion of the restricted subsystem is taken
# fully out of service and the rest of that subsystem runs at 0.2, so the instance carries a
# genuine disabled-source contingency rather than a uniform derating. In both restricted
# subsystems the disabled diversion is the smallest one (35 cfs design envelope): s_15957 in
# subsystem_03 and s_10434 in subsystem_02. Recovered from the released source_limits table.
FULL_OUTAGE_SOURCES = {"s_15957", "s_10434"}


# ------------------------------------------------------------------ geometry
#
# Point-in-polygon on the raw service-area layer, with no geospatial dependency: the whole
# selection has to be reproducible from a stock Python installation, and the only geometric
# question asked of the layer is whether an official delivery terminal falls inside a
# service polygon.

def _rings(geometry: dict) -> list:
    """The polygon parts of a GeoJSON geometry, each a list of rings, outer ring first."""

    kind = geometry["type"]
    coordinates = geometry["coordinates"]
    if kind == "Polygon":
        return [coordinates]
    if kind == "MultiPolygon":
        return coordinates
    return []


def _in_ring(x: float, y: float, ring: list) -> bool:
    """Ray casting: a point is inside a closed ring when a ray crosses it an odd number of times.

    The epsilon on the denominator only guards a horizontal edge, which the crossing test
    above has already excluded, so it changes no result; it keeps the division defined.
    """

    inside = False
    count = len(ring)
    j = count - 1
    for i in range(count):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            denominator = (yj - yi) or 1e-18
            if x < (xj - xi) * (y - yi) / denominator + xi:
                inside = not inside
        j = i
    return inside


def _in_polygon(x: float, y: float, polygon: list) -> bool:
    """Inside the outer ring of some part of the polygon and outside every hole of that part."""

    for rings in polygon:
        if _in_ring(x, y, rings[0]) and not any(_in_ring(x, y, hole) for hole in rings[1:]):
            return True
    return False


# ------------------------------------------------------------------ discovery

def discover() -> dict:
    """Select claimants, terminals and paths from the open layers.

    Every service area of the county that owns an official delivery terminal becomes a
    candidate claimant. A terminal is assigned to the first service polygon that contains
    it; a company's own terminal is the lowest-numbered node assigned to it, so the choice
    does not depend on the order the layer happens to list its nodes. A path is selected when
    its endpoint node is one of those terminals and it declares a source.
    """

    service = json.loads(gb.SERVICE_GEOJSON.read_text(encoding="utf-8"))
    polygons = [
        (feature["properties"], _rings(feature["geometry"]))
        for feature in service["features"]
        if (feature["properties"].get("COUNTY") or "").strip().lower() == COUNTY.lower()
    ]
    network = gb.NETWORK_DIR
    nodes = list(gb.read_csv(network / "0_NetNodes.csv"))
    terminals = [row for row in nodes if row["NodeType"] == "3"]

    matched: dict[str, list[dict]] = collections.defaultdict(list)
    for node in terminals:
        try:
            lon, lat = float(node["Lon"]), float(node["Lat"])
        except (TypeError, ValueError):
            continue
        for properties, polygon in polygons:
            if _in_polygon(lon, lat, polygon):
                matched[str(properties["COMPANYID"])].append(node)
                break

    point_rows: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for row in gb.read_csv(network / "3_PathPoints_Table.csv"):
        point_rows[row["PathId"]][row["PointType"]] = row["NodeId"]

    terminal_to_company = {
        node["NodeId"]: company for company, group in matched.items() for node in group
    }
    selected_paths = {
        path_id
        for path_id, endpoints in point_rows.items()
        if endpoints.get("2") in terminal_to_company and endpoints.get("1")
    }

    by_id = {str(properties["COMPANYID"]): properties for properties, _ in polygons}
    companies: dict[str, dict] = {}
    for company, group in sorted(matched.items(), key=lambda item: int(item[0])):
        node = sorted(group, key=lambda row: int(row["NodeId"]))[0]
        companies[company] = {
            "claimant_id": f"company_{int(company):03d}",
            "terminal_raw": node["NodeId"],
            "name": (by_id[company].get("COMPNAME") or f"Company {company}").strip(),
        }

    source_to_company: dict[str, set[str]] = collections.defaultdict(set)
    for path_id in selected_paths:
        endpoints = point_rows[path_id]
        source_to_company[endpoints["1"]].add(terminal_to_company[endpoints["2"]])

    return {
        "companies": companies,
        "selected_paths": sorted(selected_paths),
        "path_terminal": {path: point_rows[path]["2"] for path in sorted(selected_paths)},
        "terminal_to_company": terminal_to_company,
        "source_to_company": {key: sorted(value) for key, value in source_to_company.items()},
    }


def load_or_discover() -> dict:
    """Discovery is cached so a long build can be restarted without re-scanning.

    Deleting ``selection.json`` re-runs the pass over the raw layers, which is the check that
    the cache is a cache and not an input: the rediscovered file must be byte-identical to
    the released one.
    """

    if SELECTION.exists():
        cached = json.loads(SELECTION.read_text(encoding="utf-8"))
        if REQUIRED.issubset(cached):
            print(f"reusing cached selection: {SELECTION}")
            return cached
        print("cached selection has an older schema; rediscovering")
    print("discovering claimants, terminals and paths from the raw layers")
    discovery = discover()
    TARGET.mkdir(parents=True, exist_ok=True)
    # Newline pinned, so the file is the same bytes on every platform.
    with SELECTION.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(discovery, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"wrote {SELECTION}")
    return discovery


def unrouted_company_ids() -> set[str]:
    """Companies that the first pass found to have lost every route.

    Empty on the first pass. The report is written by the generator itself, before any
    benchmark file, so the two passes communicate through the released artefact rather than
    through an edited selection: the path set stays exactly what the acres filter produced.
    """

    if not UNROUTED.exists():
        return set()
    report = json.loads(UNROUTED.read_text(encoding="utf-8"))
    return {str(row["company_id"]) for row in report["companies"]}


# ------------------------------------------------------------------ selection filters

def qualifying_companies(companies: dict) -> tuple[dict, list[str]]:
    """Drop claimants whose service polygon receives no irrigated WRLU parcel.

    A claimant with zero net demand carries no service-ratio constraint, so keeping it
    would add an unconstrained row to the guarantee vector rather than a fairness
    subject. The exclusion is reported so the selection stays auditable.
    """

    gb.COMPANIES = companies
    parcels = gb.extract_parcels(gb.extract_service_areas())
    demand_acres: dict[str, float] = collections.defaultdict(float)
    for parcel in parcels:
        if gb.is_irrigated_demand_parcel(parcel):
            demand_acres[parcel["claimant_id"]] += float(parcel["acres"])

    kept: dict[str, dict] = {}
    dropped: list[str] = []
    for company, specification in companies.items():
        if demand_acres.get(specification["claimant_id"], 0.0) > 0.0:
            kept[company] = specification
        else:
            dropped.append(f"{specification['claimant_id']} ({specification['name']})")
    # Sorted for the same reason the unrouted report is: the cached and the rediscovered
    # selection insert the same companies in different orders.
    return kept, sorted(dropped)


# ------------------------------------------------------------------ shared source groups

def build_groups(discovery: dict) -> dict:
    """One shared operational envelope per weakly connected source-claimant block."""

    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for source, companies in discovery["source_to_company"].items():
        anchor = f"s:{source}"
        find(anchor)
        for company in companies:
            union(anchor, f"c:{company}")

    blocks: dict[str, dict[str, set]] = collections.defaultdict(
        lambda: {"sources": set(), "companies": set()}
    )
    for source, companies in discovery["source_to_company"].items():
        key = find(f"s:{source}")
        blocks[key]["sources"].add(gb.source_id(source))
        blocks[key]["companies"].update(companies)

    specs: dict[str, dict] = {}
    ordered = sorted(
        blocks.items(),
        key=lambda item: (-len(item[1]["companies"]), sorted(item[1]["sources"])),
    )
    for index, (_, block) in enumerate(ordered, start=1):
        group_id = f"subsystem_{index:02d}"
        terminal_nodes = {
            gb.node_id(node)
            for node, company in discovery["terminal_to_company"].items()
            if company in block["companies"]
        }
        specs[group_id] = {
            "label": f"Cache Valley delivery subsystem {index}",
            "source_ids": sorted(block["sources"]),
            "terminal_nodes": terminal_nodes,
        }
    return specs


# ------------------------------------------------------------------ scenarios

def build_scenarios(groups: dict) -> tuple[list[dict], dict, dict, dict]:
    """Equal-budget contingency scenarios with binding group derating."""

    ordered = sorted(groups)
    # The two subsystems that pool the most sources carry the single-subsystem restriction
    # scenarios. The surviving bytecode simply took the first two group identifiers; the
    # released benchmark restricts subsystem_03 and subsystem_02, the two largest, and that
    # is what is reproduced here.
    largest = sorted(ordered, key=lambda group: (-len(groups[group]["source_ids"]), group))[:2]

    specs = [
        {
            "scenario_id": "nominal",
            "label": "Design-envelope reference",
            "description": (
                "All selected sources and reaches are available. This scenario carries the "
                "nominal plan itself, so its recourse budget is zero by definition and it is "
                "a reference anchor rather than a comparable stress case."
            ),
            # Zero by definition: the nominal plan is what the contingencies deviate from,
            # and the validator rejects any other value. The surviving bytecode carried 0.25,
            # which predates that rule.
            "recourse_budget": 0.0,
            "probability_weight": 0.0,
        },
        {
            "scenario_id": "moderate_system_shortage",
            "label": "Moderate system shortage",
            "description": "Uniform experimental derating of every shared delivery subsystem.",
            "recourse_budget": 0.25,
            "probability_weight": 0.25,
        },
        {
            "scenario_id": "severe_system_shortage",
            "label": "Severe system shortage",
            "description": "Deep uniform derating of every shared delivery subsystem.",
            "recourse_budget": 0.25,
            "probability_weight": 0.25,
        },
    ]
    # Shared-envelope derating. These are the released levels; the group levels are not the
    # source levels, and the bytecode's 0.5/0.25 belong to the sources, not the envelopes.
    factors = {
        "nominal": {group: 1.0 for group in ordered},
        "moderate_system_shortage": {group: 0.6 for group in ordered},
        "severe_system_shortage": {group: 0.35 for group in ordered},
    }
    source_factors = {
        "nominal": {"reservoir_release": 1.0, "surface_diversion": 1.0},
        "moderate_system_shortage": {"reservoir_release": 0.5, "surface_diversion": 0.35},
        "severe_system_shortage": {"reservoir_release": 0.25, "surface_diversion": 0.15},
    }
    # No reach is restricted in the system-wide scenarios; the restriction scenarios below
    # add their own head gates.
    edge_factors: dict[str, dict[str, float]] = {
        "nominal": {},
        "moderate_system_shortage": {},
        "severe_system_shortage": {},
    }

    for position, group in enumerate(largest, start=1):
        scenario_id = f"subsystem_{position:02d}_restriction_under_shortage"
        specs.append(
            {
                "scenario_id": scenario_id,
                "label": f"Subsystem {position} restriction under shortage",
                "description": (
                    f"Shared envelope of {group} is restricted while the remaining "
                    "subsystems operate under a moderate shortage."
                ),
                "recourse_budget": 0.25,
                "probability_weight": 0.25,
            }
        )
        factors[scenario_id] = {
            candidate: (0.2 if candidate == group else 0.7) for candidate in ordered
        }
        source_factors[scenario_id] = {
            "reservoir_release": 0.7,
            "surface_diversion": 0.7,
            "overrides": {
                source: (0.0 if source in FULL_OUTAGE_SOURCES else 0.2)
                for source in sorted(groups[group]["source_ids"])
            },
        }
        edge_factors[scenario_id] = {
            HEAD_GATES[node]: RESTRICTED_HEAD_GATE_FACTOR
            for node in sorted(groups[group]["terminal_nodes"])
            if node in HEAD_GATES
        }
    return specs, factors, source_factors, edge_factors


# ------------------------------------------------------------------ driver

def main() -> None:
    discovery = load_or_discover()
    companies = discovery["companies"]
    print(f"discovered claimants: {len(companies)}")
    print(f"discovered paths    : {len(discovery['selected_paths'])}")

    companies, dropped = qualifying_companies(companies)
    print(f"excluded (no irrigated WRLU acres): {len(dropped)}")
    for item in dropped:
        print(f"   - {item}")
    print(f"qualifying claimants: {len(companies)}")

    # The path set is fixed here, by the acres filter alone, and the second pass keeps it.
    # Narrowing it to the survivors would narrow the connector candidates with it and the
    # repair would settle on a different graph, so the two passes would not agree.
    kept_terminals = {specification["terminal_raw"] for specification in companies.values()}
    discovery["selected_paths"] = sorted(
        path
        for path in discovery["selected_paths"]
        if discovery["path_terminal"].get(path) in kept_terminals
    )
    print(f"selected paths      : {len(discovery['selected_paths'])}")

    # Claimants and shared source groups come from the companies the repair leaves routed.
    # On the first pass that is every qualifying company and the build stops below; on the
    # second it is the survivors, which is the set the released groups were derived from.
    unrouted = unrouted_company_ids()
    if unrouted:
        print(f"without a route (pass 1): {len(unrouted)}")
    companies = {
        company: specification
        for company, specification in companies.items()
        if company not in unrouted
    }
    print(f"routed claimants    : {len(companies)}")
    discovery["terminal_to_company"] = {
        node: company
        for node, company in discovery["terminal_to_company"].items()
        if company in companies
    }
    discovery["source_to_company"] = {
        source: [c for c in companies_list if c in companies]
        for source, companies_list in discovery["source_to_company"].items()
        if any(c in companies for c in companies_list)
    }

    groups = build_groups(discovery)
    print(f"derived subsystems  : {len(groups)}")
    for group_id, spec in groups.items():
        print(f"   {group_id}: {len(spec['source_ids'])} sources, {len(spec['terminal_nodes'])} terminals")

    scenarios, factors, source_factors, edge_factors = build_scenarios(groups)

    gb.BENCHMARK_ID = BENCHMARK_ID
    gb.COMPANIES = companies
    gb.SELECTED_PATHS = set(discovery["selected_paths"])
    gb.SOURCE_GROUP_SPECS = groups
    gb.GROUP_SCENARIO_FACTORS = factors
    gb.SOURCE_SCENARIO_FACTORS = source_factors
    gb.EDGE_SCENARIO_FACTORS = edge_factors
    gb.SCENARIO_SPECS = scenarios
    gb.SOURCE_ROLE_NAMES = {}
    gb.EXTRA_CONTROL_EDGES = EXTRA_CONTROL_EDGES
    gb.MEASUREMENT_STATION_IDS = set()
    gb.HERE = TARGET
    gb.OUT = TARGET / "data"
    TARGET.mkdir(parents=True, exist_ok=True)

    gc.collect()
    gb.build()

    reduction = dict(gb.TOPOLOGY_REDUCTION)
    # Paths that survive the repair: the selection minus the ones a rejected connector broke.
    path_count = len(discovery["selected_paths"]) - len(reduction.get("paths_dropped", []))
    without_route = json.loads(UNROUTED.read_text(encoding="utf-8"))["companies"] if UNROUTED.exists() else []
    summary = {
        "county": COUNTY,
        "claimants": {
            company: specification["name"] for company, specification in companies.items()
        },
        "path_count": path_count,
        "excluded_no_irrigated_acres": dropped,
        "excluded_no_acyclic_path": [f"{row['claimant_id']} ({row['name']})" for row in without_route],
        "subsystems": {group_id: spec["source_ids"] for group_id, spec in groups.items()},
        "acyclic_reduction": reduction,
    }
    (TARGET / "discovery_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
