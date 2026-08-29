"""Build a reproducible Little Bear River model-input benchmark.

The script deliberately separates source observations, transparent derivations,
and experiment assumptions. It uses only Python's standard library.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import statistics
import math
import sqlite3
import struct
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from validate_benchmark import validate_payload


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATASETS = Path(os.environ.get("LEXIMIN_DATASETS", str(REPO / "DataSETs")))
OUT = HERE / "data"

BENCHMARK_ID = "lbr_hyrum_paradise_highline_2025_v2"
YEAR = 2025
CFS_DAY_TO_AF = 1.9834710743801653

NETWORK_DIR = DATASETS / "Utah_Distribution_Network_2026" / "csv"
CANALS_CSV = DATASETS / "Utah Canals" / "UDNR.WRT.Canals_CFS.csv"
SERVICE_GEOJSON = DATASETS / "Utah Irrigation Company Service Areas" / "utah_service_areas.geojson"
WRLU_GPKG = next((DATASETS / "WaterRelatedLandUse_2025").glob("*.gpkg"))

COMPANIES = {
    "88": {
        "claimant_id": "company_088",
        "terminal_raw": "16801",
        "name": "Hyrum Irrigation Co.",
    },
    "130": {
        "claimant_id": "company_130",
        "terminal_raw": "16802",
        "name": "Paradise Irrigation Co.",
    },
    "132": {
        "claimant_id": "company_132",
        "terminal_raw": "16803",
        "name": "Porcupine Highline Canal Co.",
    },
}

SELECTED_PATHS = {
    "4115", "4116", "4117", "4118", "4119", "4127",
    "4120", "4121", "4122", "4123", "4125", "4124",
}

PERIOD_SPECS = [
    ("2025-05", 31, 0.12),
    ("2025-06", 30, 0.22),
    ("2025-07", 31, 0.28),
    ("2025-08", 31, 0.24),
    ("2025-09", 30, 0.14),
]

# Net seasonal demand is a benchmark assumption, not a WRLU measurement.
DEMAND_DUTY_AF_PER_ACRE = 2.0
CANAL_LOSS_RATE_PER_KM = 0.005
STREAM_LOSS_RATE_PER_KM = 0.001

# Application-efficiency assumptions are used only after the terminal withdrawal.
# The claimant coefficient is the crop-area weighted harmonic mean, which preserves
# the gross water required to meet a common net duty across methods.
IRRIGATION_METHOD_EFFICIENCY = {
    "Drip": 0.90,
    "Flood": 0.60,
    "Pivot": 0.85,
    "Sprinkler": 0.75,
    "Sub-irrigated": 0.65,
    "Wheel": 0.78,
}
NON_IRRIGATED_METHODS = {"Dry Crop"}
NON_DEMAND_CROP_GROUPS = {"Fallow/Idle"}

SOURCE_GROUP_SPECS = {
    "hyrum_subsystem": {
        "label": "Hyrum delivery subsystem",
        "source_ids": {"s_15269", "s_15957"},
        "terminal_nodes": {"n_16801"},
    },
    "paradise_highline_subsystem": {
        "label": "Paradise-Highline delivery subsystem",
        "source_ids": {"s_10434", "s_15286"},
        "terminal_nodes": {"n_16802", "n_16803"},
    },
}

GROUP_SCENARIO_FACTORS = {
    "nominal": {"hyrum_subsystem": 1.00, "paradise_highline_subsystem": 1.00},
    "moderate_system_shortage": {"hyrum_subsystem": 0.22, "paradise_highline_subsystem": 0.42},
    "severe_system_shortage": {"hyrum_subsystem": 0.12, "paradise_highline_subsystem": 0.22},
    "paradise_diversion_outage_under_shortage": {"hyrum_subsystem": 0.35, "paradise_highline_subsystem": 0.32},
    "hyrum_canal_restriction_under_shortage": {"hyrum_subsystem": 0.18, "paradise_highline_subsystem": 0.50},
}

# Claimant-specific operational role labels for (source, claimant) pairs. Pairs that are
# not listed fall back to _derived_source_role, so the generator scales to any claimant set.
SOURCE_ROLE_NAMES = {
    ("s_15269", "company_088"): "supplemental_storage_release",
    ("s_15957", "company_088"): "routine_surface_diversion",
    ("s_10434", "company_130"): "routine_surface_diversion",
    ("s_15286", "company_130"): "supplemental_storage_release",
    ("s_15286", "company_132"): "routine_storage_supply",
}

# Physical branch/head gates promoted to recourse control assets, in addition to sources.
EXTRA_CONTROL_EDGES = [
    ("e_3577", "Highline branch gate"),
    ("e_5854", "Paradise branch gate"),
    ("e_10136", "Paradise Canal head gate"),
]


def _derived_source_role(source_class: str, source_count: int) -> str:
    """Role label for a (source, claimant) pair that is not explicitly named.

    A claimant served by a single source uses it routinely; a claimant with several
    sources treats storage releases as supplemental to routine surface diversions.
    """

    if source_class == "reservoir_release":
        return "routine_storage_supply" if source_count == 1 else "supplemental_storage_release"
    return "routine_surface_diversion"


SCENARIO_SPECS = [
    {
        "scenario_id": "nominal",
        "label": "Design-envelope reference",
        "description": "All selected sources and reaches are available.",
        "recourse_budget": 0.0,
        "probability_weight": 0.0,
    },
    {
        "scenario_id": "moderate_system_shortage",
        "label": "Moderate system shortage",
        "description": "Experimental shared-system, surface-diversion and storage-release derating.",
        "recourse_budget": 0.25,
        "probability_weight": 0.25,
    },
    {
        "scenario_id": "severe_system_shortage",
        "label": "Severe system shortage",
        "description": "Non-nested experimental stress with a low shared-system envelope.",
        "recourse_budget": 0.40,
        "probability_weight": 0.25,
    },
    {
        "scenario_id": "paradise_diversion_outage_under_shortage",
        "label": "Paradise diversion outage under shortage",
        "description": "The local Paradise diversion is disabled while the storage route remains available.",
        "recourse_budget": 0.35,
        "probability_weight": 0.25,
    },
    {
        "scenario_id": "hyrum_canal_restriction_under_shortage",
        "label": "Hyrum canal restriction under shortage",
        "description": "Hyrum Canal head capacity and both local sources are derated without disconnecting the claimant.",
        "recourse_budget": 0.25,
        "probability_weight": 0.25,
    },
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def round_float(value: float, digits: int = 9) -> float:
    return round(float(value), digits)


def node_id(raw: str) -> str:
    return f"n_{raw}"


def edge_id(raw: str) -> str:
    return f"e_{raw}"


def source_id(raw: str) -> str:
    return f"s_{raw}"


def normalize_name(value: str) -> str:
    return " ".join(value.lower().replace("'", "").replace("-", " ").split())


class WKBReader:
    def __init__(self, data: bytes, offset: int) -> None:
        self.data = data
        self.offset = offset

    def _unpack(self, fmt: str, endian: str) -> tuple[Any, ...]:
        size = struct.calcsize(endian + fmt)
        values = struct.unpack_from(endian + fmt, self.data, self.offset)
        self.offset += size
        return values

    def geometry(self) -> list[list[list[tuple[float, float]]]]:
        byte_order = self.data[self.offset]
        self.offset += 1
        endian = "<" if byte_order == 1 else ">"
        raw_type = self._unpack("I", endian)[0]

        ewkb_z = bool(raw_type & 0x80000000)
        ewkb_m = bool(raw_type & 0x40000000)
        has_srid = bool(raw_type & 0x20000000)
        plain_type = raw_type & 0x1FFFFFFF
        if plain_type >= 3000:
            dimensions, base_type = 4, plain_type - 3000
        elif plain_type >= 2000:
            dimensions, base_type = 3, plain_type - 2000
        elif plain_type >= 1000:
            dimensions, base_type = 3, plain_type - 1000
        else:
            dimensions = 2 + int(ewkb_z) + int(ewkb_m)
            base_type = plain_type
        if has_srid:
            self._unpack("I", endian)

        def point() -> tuple[float, float]:
            values = self._unpack("d" * dimensions, endian)
            return float(values[0]), float(values[1])

        if base_type == 3:  # Polygon
            ring_count = self._unpack("I", endian)[0]
            rings: list[list[tuple[float, float]]] = []
            for _ in range(ring_count):
                count = self._unpack("I", endian)[0]
                rings.append([point() for _ in range(count)])
            return [rings]
        if base_type in {6, 7}:  # MultiPolygon / GeometryCollection
            count = self._unpack("I", endian)[0]
            polygons: list[list[list[tuple[float, float]]]] = []
            for _ in range(count):
                polygons.extend(self.geometry())
            return polygons
        raise ValueError(f"Unsupported WRLU WKB geometry type: {base_type}")


def gpkg_polygons(blob: bytes) -> list[list[list[tuple[float, float]]]]:
    if blob[:2] != b"GP":
        raise ValueError("Invalid GeoPackage geometry header.")
    flags = blob[3]
    envelope_code = (flags >> 1) & 0x07
    envelope_values = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}.get(envelope_code)
    if envelope_values is None:
        raise ValueError(f"Unsupported GeoPackage envelope code: {envelope_code}")
    return WKBReader(blob, 8 + envelope_values * 8).geometry()


def polygon_centroid(polygons: list[list[list[tuple[float, float]]]]) -> tuple[float, float]:
    weighted_x = 0.0
    weighted_y = 0.0
    total_mass = 0.0
    fallback: list[tuple[float, float]] = []
    for polygon in polygons:
        for ring_index, ring in enumerate(polygon):
            fallback.extend(ring)
            cross_sum = 0.0
            cx_sum = 0.0
            cy_sum = 0.0
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                cross = x1 * y2 - x2 * y1
                cross_sum += cross
                cx_sum += (x1 + x2) * cross
                cy_sum += (y1 + y2) * cross
            if abs(cross_sum) < 1e-12:
                continue
            area = cross_sum / 2.0
            cx = cx_sum / (6.0 * area)
            cy = cy_sum / (6.0 * area)
            mass = abs(area) if ring_index == 0 else -abs(area)
            weighted_x += cx * mass
            weighted_y += cy * mass
            total_mass += mass
    if abs(total_mass) < 1e-9:
        if not fallback:
            raise ValueError("Empty WRLU geometry.")
        return (
            sum(point[0] for point in fallback) / len(fallback),
            sum(point[1] for point in fallback) / len(fallback),
        )
    return weighted_x / total_mass, weighted_y / total_mass


def lonlat_to_utm12(lon: float, lat: float) -> tuple[float, float]:
    # WGS84 / UTM zone 12N; adequate for the local point-in-polygon join.
    a = 6378137.0
    ecc_squared = 0.00669438
    k0 = 0.9996
    ecc_prime_squared = ecc_squared / (1.0 - ecc_squared)
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    origin_rad = math.radians(-111.0)
    n = a / math.sqrt(1.0 - ecc_squared * math.sin(lat_rad) ** 2)
    t = math.tan(lat_rad) ** 2
    c = ecc_prime_squared * math.cos(lat_rad) ** 2
    aa = math.cos(lat_rad) * (lon_rad - origin_rad)
    m = a * (
        (1 - ecc_squared / 4 - 3 * ecc_squared**2 / 64 - 5 * ecc_squared**3 / 256) * lat_rad
        - (3 * ecc_squared / 8 + 3 * ecc_squared**2 / 32 + 45 * ecc_squared**3 / 1024)
        * math.sin(2 * lat_rad)
        + (15 * ecc_squared**2 / 256 + 45 * ecc_squared**3 / 1024) * math.sin(4 * lat_rad)
        - (35 * ecc_squared**3 / 3072) * math.sin(6 * lat_rad)
    )
    easting = k0 * n * (
        aa
        + (1 - t + c) * aa**3 / 6
        + (5 - 18 * t + t**2 + 72 * c - 58 * ecc_prime_squared) * aa**5 / 120
    ) + 500000.0
    northing = k0 * (
        m
        + n
        * math.tan(lat_rad)
        * (
            aa**2 / 2
            + (5 - t + 9 * c + 4 * c**2) * aa**4 / 24
            + (61 - 58 * t + t**2 + 600 * c - 330 * ecc_prime_squared) * aa**6 / 720
        )
    )
    return easting, northing


def project_geojson_geometry(geometry: dict[str, Any]) -> list[list[list[tuple[float, float]]]]:
    coordinates = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        coordinates = [coordinates]
    if geometry["type"] != "MultiPolygon" and geometry["type"] != "Polygon":
        raise ValueError(f"Unsupported service-area geometry: {geometry['type']}")
    return [
        [[lonlat_to_utm12(float(lon), float(lat)) for lon, lat, *_ in ring] for ring in polygon]
        for polygon in coordinates
    ]


def point_on_segment(x: float, y: float, a: tuple[float, float], b: tuple[float, float]) -> bool:
    cross = (x - a[0]) * (b[1] - a[1]) - (y - a[1]) * (b[0] - a[0])
    if abs(cross) > 1e-7:
        return False
    return min(a[0], b[0]) - 1e-7 <= x <= max(a[0], b[0]) + 1e-7 and min(
        a[1], b[1]
    ) - 1e-7 <= y <= max(a[1], b[1]) + 1e-7


def point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    for a, b in zip(ring, ring[1:]):
        if point_on_segment(x, y, a, b):
            return True
        if (a[1] > y) != (b[1] > y):
            intersection_x = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < intersection_x:
                inside = not inside
    return inside


def point_in_multipolygon(
    x: float, y: float, polygons: list[list[list[tuple[float, float]]]]
) -> bool:
    for polygon in polygons:
        if polygon and point_in_ring(x, y, polygon[0]) and not any(
            point_in_ring(x, y, hole) for hole in polygon[1:]
        ):
            return True
    return False


def bbox(polygons: list[list[list[tuple[float, float]]]]) -> tuple[float, float, float, float]:
    points = [point for polygon in polygons for ring in polygon for point in ring]
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def extract_service_areas() -> dict[str, dict[str, Any]]:
    with SERVICE_GEOJSON.open(encoding="utf-8") as stream:
        data = json.load(stream)
    selected: dict[str, dict[str, Any]] = {}
    for feature in data["features"]:
        company = str(feature["properties"].get("COMPANYID", ""))
        if company not in COMPANIES:
            continue
        polygons = project_geojson_geometry(feature["geometry"])
        selected[company] = {
            "properties": feature["properties"],
            "polygons": polygons,
            "bbox": bbox(polygons),
        }
    if set(selected) != set(COMPANIES):
        raise ValueError("One or more selected service areas are missing.")
    return selected


def extract_parcels(service_areas: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    query = """
        SELECT OBJECTID, SHAPE, Landuse, CropGroup, Description, IRR_Method,
               Acres, State, County, Basin, SubArea, SURV_YEAR
        FROM WaterRelatedLandUse_2025
        WHERE Landuse = 'Agricultural' AND County = 'Cache' AND SURV_YEAR = '2025'
        ORDER BY OBJECTID
    """
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(WRLU_GPKG) as connection:
        for record in connection.execute(query):
            objectid, geometry_blob, landuse, crop, description, irrigation, acres, state, county, basin, subarea, survey_year = record
            x, y = polygon_centroid(gpkg_polygons(geometry_blob))
            candidates: list[str] = []
            for company, area in service_areas.items():
                minx, miny, maxx, maxy = area["bbox"]
                if minx <= x <= maxx and miny <= y <= maxy and point_in_multipolygon(
                    x, y, area["polygons"]
                ):
                    candidates.append(company)
            if not candidates:
                continue
            candidates.sort(key=lambda company: float(service_areas[company]["properties"]["ACRES"]))
            company = candidates[0]
            rows.append(
                {
                    "claimant_id": COMPANIES[company]["claimant_id"],
                    "wrlu_objectid": int(objectid),
                    "landuse": landuse or "",
                    "crop_group": crop or "Unspecified",
                    "description": description or "",
                    "irrigation_method": irrigation or "Unspecified",
                    "acres": round_float(acres, 6),
                    "survey_year": str(survey_year),
                    "county": county or "",
                    "basin": basin or "",
                    "subarea": subarea or "",
                    "centroid_x_epsg26912": round_float(x, 3),
                    "centroid_y_epsg26912": round_float(y, 3),
                    "assignment_method": "area_weighted_polygon_centroid_in_simplified_service_area",
                    "assignment_candidate_count": len(candidates),
                }
            )
    return rows


# Populated by extract_network when the derived-connector repair has to reject a
# candidate. It stays empty whenever the path table needs no acyclic reduction, so
# benchmarks that were already acyclic are byte-for-byte unaffected.
TOPOLOGY_REDUCTION: dict[str, Any] = {}


def acyclic_connector_selection(
    physical_edges: dict[str, dict[str, Any]],
    candidate_pairs: Mapping[tuple[str, str], list[float]],
) -> tuple[set[tuple[str, str]], list[dict[str, str]]]:
    """Accept derived gap connectors only while the graph stays acyclic.

    The official reach topology is acyclic on its own. Cycles appear only when the
    path table is repaired by bridging a gap with a logical connector, because two
    paths may need bridges that together close a loop. Candidates are considered in a
    deterministic node order and a candidate is rejected when its head can already
    reach its tail, which is precisely the condition for closing a cycle.
    """

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in physical_edges.values():
        adjacency[edge["from_node"]].add(edge["to_node"])

    def reaches(start: str, target: str) -> bool:
        seen = {start}
        stack = [start]
        while stack:
            node = stack.pop()
            for following in adjacency.get(node, ()):
                if following == target:
                    return True
                if following not in seen:
                    seen.add(following)
                    stack.append(following)
        return False

    # Bridges that more paths depend on are considered first, so a rejection removes as
    # few source-terminal paths as possible. Ties break on node order for determinism.
    accepted: set[tuple[str, str]] = set()
    rejected: list[dict[str, str]] = []
    order = sorted(
        candidate_pairs,
        key=lambda item: (-len(candidate_pairs[item]), int(item[0]), int(item[1])),
    )
    for pair in order:
        tail, head = node_id(pair[0]), node_id(pair[1])
        if tail == head:
            rejected.append({"connector": f"c_{pair[0]}_{pair[1]}", "reason": "self_loop"})
            continue
        if reaches(head, tail):
            rejected.append({"connector": f"c_{pair[0]}_{pair[1]}", "reason": "would_close_a_cycle"})
            continue
        accepted.add(pair)
        adjacency[tail].add(head)
    return accepted, rejected


def extract_network() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    node_rows = {row["NodeId"]: row for row in read_csv(NETWORK_DIR / "0_NetNodes.csv")}
    flow_rows = {row["recordId"]: row for row in read_csv(NETWORK_DIR / "1_Net_Flowlines.csv")}
    point_rows = [
        row for row in read_csv(NETWORK_DIR / "3_PathPoints_Table.csv") if row["PathId"] in SELECTED_PATHS
    ]
    path_rows = {
        row["recordId"]: row
        for row in read_csv(NETWORK_DIR / "4_NetPaths_Table.csv")
        if row["recordId"] in SELECTED_PATHS
    }
    pathline_rows = [
        row for row in read_csv(NETWORK_DIR / "5_NetPathlines_Table.csv") if row["PathId"] in SELECTED_PATHS
    ]

    path_points: dict[str, dict[str, str]] = defaultdict(dict)
    for row in point_rows:
        path_points[row["PathId"]][row["PointType"]] = row["NodeId"]
    lines_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pathline_rows:
        lines_by_path[row["PathId"]].append(row)
    for lines in lines_by_path.values():
        lines.sort(key=lambda row: int(row["SortOrder"]))

    canal_capacities: dict[str, set[float]] = defaultdict(set)
    for row in read_csv(CANALS_CSV):
        if row["CompanyID"] in COMPANIES and row["MaxCFS"]:
            canal_capacities[normalize_name(row["Canal"])].add(float(row["MaxCFS"]))

    physical_ids = {row["FlowlineID"] for row in pathline_rows}

    # Capacity evidence is assigned in three declared tiers. Tier 1 and tier 2 are
    # per-reach; tier 3 exists because a small number of officially named reaches carry
    # neither an exact-name MaxCFS join nor a RelativeSize attribute. Those reaches
    # inherit the minimum known capacity of the paths that traverse them, which is the
    # same conservative rule already applied to derived path connectors.
    capacity_by_raw: dict[str, tuple[float, str, str]] = {}
    pending: list[str] = []
    for raw in sorted(physical_ids, key=int):
        row = flow_rows[raw]
        name_key = normalize_name(row["FlowlineName"])
        matching = canal_capacities.get(name_key, set()) if row["FlowlineType"] == "1" else set()
        if len(matching) == 1:
            capacity_by_raw[raw] = (
                next(iter(matching)),
                "Utah_Canals.MaxCFS_exact_name_join",
                "observed_design_attribute",
            )
        elif row["RelativeSize"]:
            capacity_by_raw[raw] = (
                float(row["RelativeSize"]),
                "Distribution_Network.RelativeSize_used_as_CFS_proxy",
                "proxy_requires_calibration",
            )
        else:
            pending.append(raw)

    if pending:
        paths_of_flowline: dict[str, set[str]] = defaultdict(set)
        flowlines_of_path: dict[str, set[str]] = defaultdict(set)
        for line in pathline_rows:
            paths_of_flowline[line["FlowlineID"]].add(line["PathId"])
            flowlines_of_path[line["PathId"]].add(line["FlowlineID"])
        known = [value[0] for value in capacity_by_raw.values()]
        if not known:
            raise ValueError("No reach in the selection carries a capacity basis.")
        fallback = statistics.median(known)
        for raw in pending:
            neighbours = [
                capacity_by_raw[other][0]
                for path in paths_of_flowline[raw]
                for other in flowlines_of_path[path]
                if other in capacity_by_raw
            ]
            capacity_by_raw[raw] = (
                min(neighbours) if neighbours else fallback,
                "derived_minimum_capacity_of_traversing_paths"
                if neighbours
                else "derived_median_capacity_of_selected_reaches",
                "derived_requires_calibration",
            )

    physical_edges: dict[str, dict[str, Any]] = {}
    for raw in sorted(physical_ids, key=int):
        row = flow_rows[raw]
        capacity, capacity_basis, capacity_status = capacity_by_raw[raw]
        length_m = float(row["Shape__Length"])
        kind = "stream" if row["FlowlineType"] == "0" else "canal"
        rate = STREAM_LOSS_RATE_PER_KM if kind == "stream" else CANAL_LOSS_RATE_PER_KM
        eta = math.exp(-rate * length_m / 1000.0)
        physical_edges[edge_id(raw)] = {
            "edge_id": edge_id(raw),
            "source_record_id": int(raw),
            "from_node": node_id(row["FromNode"]),
            "to_node": node_id(row["ToNode"]),
            "edge_role": "physical",
            "flowline_type": kind,
            "flowline_name": row["FlowlineName"],
            "length_m": round_float(length_m, 6),
            "capacity_cfs_base": round_float(capacity, 6),
            "capacity_basis": capacity_basis,
            "capacity_status": capacity_status,
            "efficiency_base": round_float(eta, 9),
            "efficiency_basis": f"assumed_exp_length_decay_{rate}_per_km",
            "valid_in_2025": True,
        }

    connector_candidates: dict[tuple[str, str], list[float]] = defaultdict(list)
    path_edge_rows: list[dict[str, Any]] = []
    paths: list[dict[str, Any]] = []
    path_plans: list[dict[str, Any]] = []

    for path_raw in sorted(SELECTED_PATHS, key=int):
        source_raw = path_points[path_raw]["1"]
        terminal_raw = path_points[path_raw]["2"]
        sequence: list[tuple[str, str]] = []
        current = source_raw
        previous_capacity: float | None = None
        for line in lines_by_path[path_raw]:
            raw_edge = line["FlowlineID"]
            source_edge = flow_rows[raw_edge]
            if line["FlowDir"] == "1":
                u, v = source_edge["FromNode"], source_edge["ToNode"]
            else:
                u, v = source_edge["ToNode"], source_edge["FromNode"]
            physical = physical_edges[edge_id(raw_edge)]
            if current != u:
                connector = f"c_{current}_{u}"
                candidate = float(physical["capacity_cfs_base"])
                if previous_capacity is not None:
                    candidate = min(candidate, previous_capacity)
                connector_candidates[(current, u)].append(candidate)
                sequence.append((connector, "derived_gap_connector"))
            sequence.append((edge_id(raw_edge), "physical_pathline"))
            current = v
            previous_capacity = float(physical["capacity_cfs_base"])
        if current != terminal_raw:
            connector = f"c_{current}_{terminal_raw}"
            if previous_capacity is None:
                raise ValueError(f"Path {path_raw} has no physical edge.")
            connector_candidates[(current, terminal_raw)].append(previous_capacity)
            sequence.append((connector, "derived_terminal_connector"))

        path_plans.append(
            {
                "path_raw": path_raw,
                "source_raw": source_raw,
                "terminal_raw": terminal_raw,
                "sequence": sequence,
            }
        )

    accepted_connectors, rejected_connectors = acyclic_connector_selection(
        physical_edges, connector_candidates
    )
    rejected_ids = {row["connector"] for row in rejected_connectors}
    dropped_paths: list[dict[str, str]] = []
    retained_source_raws: set[str] = set()
    for plan in path_plans:
        blocking = sorted(
            {identifier for identifier, _ in plan["sequence"] if identifier in rejected_ids}
        )
        if blocking:
            dropped_paths.append(
                {
                    "path_id": f"p_{plan['path_raw']}",
                    "terminal_node": node_id(plan["terminal_raw"]),
                    "blocking_connectors": "|".join(blocking),
                }
            )
            continue
        path_raw = plan["path_raw"]
        source_raw = plan["source_raw"]
        terminal_raw = plan["terminal_raw"]
        retained_source_raws.add(source_raw)
        wrnum = path_rows[path_raw]["wrnum"]
        paths.append(
            {
                "path_id": f"p_{path_raw}",
                "source_id": source_id(source_raw),
                "source_node": node_id(source_raw),
                "terminal_node": node_id(terminal_raw),
                "water_right_number": wrnum,
                "path_type": int(path_rows[path_raw]["PathType"]),
                "valid_in_2025": True,
            }
        )
        for order, (selected_edge, relation) in enumerate(plan["sequence"], start=1):
            path_edge_rows.append(
                {
                    "path_id": f"p_{path_raw}",
                    "sequence": order,
                    "edge_id": selected_edge,
                    "relation": relation,
                    "source_node": node_id(source_raw),
                    "terminal_node": node_id(terminal_raw),
                    "water_right_number": wrnum,
                }
            )

    if rejected_connectors or dropped_paths:
        TOPOLOGY_REDUCTION.clear()
        TOPOLOGY_REDUCTION.update(
            {
                "rule": "derived gap connectors are accepted only while the graph stays acyclic",
                "physical_reach_topology_is_acyclic": True,
                "connector_candidates": len(connector_candidates),
                "connectors_rejected": rejected_connectors,
                "paths_dropped": dropped_paths,
            }
        )

    # Retain only the reaches and connectors that a surviving path still traverses.
    used_edges = {row["edge_id"] for row in path_edge_rows}
    physical_edges = {
        identifier: edge for identifier, edge in physical_edges.items() if identifier in used_edges
    }
    connector_candidates = {
        pair: values
        for pair, values in connector_candidates.items()
        if pair in accepted_connectors and f"c_{pair[0]}_{pair[1]}" in used_edges
    }

    connector_edges: dict[str, dict[str, Any]] = {}
    for (u, v), candidates in sorted(connector_candidates.items(), key=lambda item: (int(item[0][0]), int(item[0][1]))):
        identifier = f"c_{u}_{v}"
        capacity = min(candidates)
        connector_edges[identifier] = {
            "edge_id": identifier,
            "source_record_id": "",
            "from_node": node_id(u),
            "to_node": node_id(v),
            "edge_role": "derived_connector",
            "flowline_type": "logical_connector",
            "flowline_name": "Path-table topology connector",
            "length_m": 0.0,
            "capacity_cfs_base": round_float(capacity, 6),
            "capacity_basis": "minimum_adjacent_path_capacity",
            "capacity_status": "derived_topology_repair",
            "efficiency_base": 1.0,
            "efficiency_basis": "lossless_logical_connector",
            "valid_in_2025": True,
        }

    edges = list(physical_edges.values()) + list(connector_edges.values())
    edge_lookup = {row["edge_id"]: row for row in edges}

    raw_node_ids = {
        endpoint[2:]
        for edge in edges
        for endpoint in (edge["from_node"], edge["to_node"])
    }
    source_nodes = {row["source_node"] for row in paths}
    terminal_nodes = {row["terminal_node"] for row in paths}
    nodes: list[dict[str, Any]] = []
    for raw in sorted(raw_node_ids, key=int):
        source = node_rows[raw]
        identifier = node_id(raw)
        roles: list[str] = []
        if identifier in source_nodes:
            roles.append("source_injection")
        if identifier in terminal_nodes:
            roles.append("delivery_terminal")
        if not roles or identifier in source_nodes and any(edge["to_node"] == identifier for edge in edges):
            roles.append("junction")
        nodes.append(
            {
                "node_id": identifier,
                "source_node_id": int(raw),
                "node_name": source["NodeName"],
                "node_type_code": int(source["NodeType"]),
                "roles": "|".join(roles),
                "latitude": round_float(source["Lat"], 8),
                "longitude": round_float(source["Lon"], 8),
                "system_id": int(source["systemId"]) if source["systemId"] else "",
                "pou_polygon_id": int(source["PouPolygonId"]) if source["PouPolygonId"] else "",
            }
        )

    # Check every augmented path is continuous before publishing it.
    for path in paths:
        selected = sorted(
            (row for row in path_edge_rows if row["path_id"] == path["path_id"]),
            key=lambda row: row["sequence"],
        )
        current = path["source_node"]
        for relation in selected:
            edge = edge_lookup[relation["edge_id"]]
            if edge["from_node"] != current:
                raise ValueError(f"Path {path['path_id']} remains discontinuous.")
            current = edge["to_node"]
        if current != path["terminal_node"]:
            raise ValueError(f"Path {path['path_id']} does not reach its terminal.")

    source_rows: list[dict[str, Any]] = []
    # Sources are taken from the retained paths, so an injection whose every path was
    # removed by the acyclic reduction does not survive as a dangling source.
    for raw in sorted(retained_source_raws, key=int):
        node = node_rows[raw]
        outgoing = [edge for edge in edges if edge["from_node"] == node_id(raw)]
        if not outgoing:
            raise ValueError(f"Source node {raw} has no outgoing selected edge.")
        design_capacity = sum(float(edge["capacity_cfs_base"]) for edge in outgoing)
        reservoir = node["NodeType"] == "1"
        source_rows.append(
            {
                "source_id": source_id(raw),
                "node_id": node_id(raw),
                "source_name": node["NodeName"] or f"Surface diversion at node {raw}",
                "source_class": "reservoir_release" if reservoir else "surface_diversion",
                "design_envelope_cfs": round_float(design_capacity, 6),
                "limit_basis": "sum_of_selected_outgoing_edge_design_or_proxy_capacity",
                "limit_status": "derived_envelope_not_observed_2025_supply",
            }
        )

    return nodes, edges, source_rows, paths, path_edge_rows


MEASUREMENT_STATION_IDS = {"2771", "2772", "2776", "9738", "9739"}


def extract_measurement_stations(selected_edges: set[str]) -> list[dict[str, Any]]:
    target = set(MEASUREMENT_STATION_IDS)
    rows: list[dict[str, Any]] = []
    for row in read_csv(NETWORK_DIR / "6_Measurement_Stations.csv"):
        if row["STATION_ID"] not in target:
            continue
        linked = edge_id(row["FlowlineId"]) if row["FlowlineId"] else ""
        rows.append(
            {
                "station_id": int(row["STATION_ID"]),
                "station_name": row["STATION_NAME"].strip(),
                "linked_edge_id": linked if linked in selected_edges else "",
                "flowline_record_id": int(row["FlowlineId"]) if row["FlowlineId"] else "",
                "status": row["STATUS"],
                "units": row["UNITS_DESC_BASE"],
                "latitude": round_float(row["latitude"], 8),
                "longitude": round_float(row["longitude"], 8),
                "url_2025": row["URL"].replace("RECORD_YEAR=2026", "RECORD_YEAR=2025"),
                "use_in_v1": False,
                "note": "Calibration target; no time-series values are embedded in v1.",
            }
        )
    return sorted(rows, key=lambda row: row["station_id"])


def is_irrigated_demand_parcel(parcel: dict[str, Any]) -> bool:
    return (
        parcel["irrigation_method"] not in NON_IRRIGATED_METHODS
        and parcel["crop_group"] not in NON_DEMAND_CROP_GROUPS
    )


# Optional per-scenario source derating table. When set, it fully replaces the built-in
# Little Bear scenario chain below, so a driver can define its own scenario set without
# editing this module. Shape:
#   {scenario_id: {"reservoir_release": f, "surface_diversion": f,
#                  "overrides": {source_id: f}}}
SOURCE_SCENARIO_FACTORS: dict[str, dict[str, Any]] | None = None

# Optional per-scenario reach capacity derating, keyed scenario -> edge -> factor.
# When set it replaces the built-in Little Bear canal-restriction rule.
EDGE_SCENARIO_FACTORS: dict[str, dict[str, float]] | None = None


def source_availability_factor(scenario_id: str, source: dict[str, Any]) -> float:
    source_class = source["source_class"]
    source_id_value = source["source_id"]
    if SOURCE_SCENARIO_FACTORS is not None:
        try:
            specification = SOURCE_SCENARIO_FACTORS[scenario_id]
        except KeyError:
            raise ValueError(f"Unknown scenario {scenario_id!r}.") from None
        overrides = specification.get("overrides", {})
        if source_id_value in overrides:
            return float(overrides[source_id_value])
        return float(specification[source_class])
    if scenario_id == "nominal":
        return 1.0
    if scenario_id == "moderate_system_shortage":
        return 0.50 if source_class == "reservoir_release" else 0.35
    if scenario_id == "severe_system_shortage":
        return 0.25 if source_class == "reservoir_release" else 0.15
    if scenario_id == "paradise_diversion_outage_under_shortage":
        if source_id_value == "s_10434":
            return 0.0
        if source_id_value == "s_15286":
            return 0.55
        return 1.0
    if scenario_id == "hyrum_canal_restriction_under_shortage":
        if source_id_value == "s_15269":
            return 0.30
        if source_id_value == "s_15957":
            return 0.25
        return 1.0
    raise ValueError(f"Unknown scenario {scenario_id!r}.")


def reachable_nodes(start: str, edges: list[dict[str, Any]]) -> set[str]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        outgoing[edge["from_node"]].append(edge["to_node"])
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nxt in outgoing.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def build() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    service_areas = extract_service_areas()
    parcels = extract_parcels(service_areas)
    nodes, edges, sources, paths, path_edges = extract_network()

    acres_by_claimant: dict[str, float] = defaultdict(float)
    demand_acres_by_claimant: dict[str, float] = defaultdict(float)
    demand_acres_by_method: dict[tuple[str, str], float] = defaultdict(float)
    parcel_count_by_claimant: dict[str, int] = defaultdict(int)
    for parcel in parcels:
        claimant_id = parcel["claimant_id"]
        acres = float(parcel["acres"])
        acres_by_claimant[claimant_id] += acres
        parcel_count_by_claimant[claimant_id] += 1
        if is_irrigated_demand_parcel(parcel):
            method = parcel["irrigation_method"]
            if method not in IRRIGATION_METHOD_EFFICIENCY:
                raise ValueError(f"No application efficiency for irrigation method {method!r}.")
            demand_acres_by_claimant[claimant_id] += acres
            demand_acres_by_method[(claimant_id, method)] += acres

    application_efficiency_by_claimant: dict[str, float] = {}
    for specification in COMPANIES.values():
        claimant_id = specification["claimant_id"]
        active_acres = demand_acres_by_claimant[claimant_id]
        gross_equivalent_acres = sum(
            acres / IRRIGATION_METHOD_EFFICIENCY[method]
            for (candidate, method), acres in demand_acres_by_method.items()
            if candidate == claimant_id
        )
        if active_acres <= 0 or gross_equivalent_acres <= 0:
            raise ValueError(f"Claimant {claimant_id} has no irrigated-demand acres.")
        application_efficiency_by_claimant[claimant_id] = active_acres / gross_equivalent_acres

    claimants: list[dict[str, Any]] = []
    claimant_terminals: list[dict[str, Any]] = []
    for company, specification in COMPANIES.items():
        properties = service_areas[company]["properties"]
        claimant = specification["claimant_id"]
        claimants.append(
            {
                "claimant_id": claimant,
                "claimant_name": specification["name"],
                "claimant_kind": "irrigation_company_service_area",
                "individual_farmer_identity_available": False,
                "company_id": int(company),
                "service_polygon_objectid": int(properties["OBJECTID"]),
                "service_area_dataset_acres": round_float(properties["ACRES"], 6),
                "assigned_wrlu_acres": round_float(acres_by_claimant[claimant], 6),
                "irrigated_demand_acres": round_float(demand_acres_by_claimant[claimant], 6),
                "excluded_nonirrigated_acres": round_float(
                    acres_by_claimant[claimant] - demand_acres_by_claimant[claimant], 6
                ),
                "assigned_wrlu_polygons": parcel_count_by_claimant[claimant],
                "water_rights_text": properties.get("WATERRGHTS") or "",
                "measurement_station_ids": properties.get("STATION_ID") or "",
                "county": properties.get("COUNTY") or "",
                "basin": properties.get("BASIN") or "",
                "subarea": properties.get("SUBAREA") or "",
            }
        )
        claimant_terminals.append(
            {
                "terminal_id": f"terminal_{claimant}_1",
                "claimant_id": claimant,
                "terminal_node": node_id(specification["terminal_raw"]),
                "terminal_share": 1.0,
                "mapping_basis": "official_distribution_terminal_name_matched_to_company_service_area",
                "mapping_status": "observed_company_level_not_farmer_level",
            }
        )

    periods = [
        {
            "period_id": identifier,
            "sequence": index,
            "days": days,
            "seasonal_demand_share": share,
        }
        for index, (identifier, days, share) in enumerate(PERIOD_SPECS, start=1)
    ]
    demands: list[dict[str, Any]] = []
    for claimant in claimants:
        seasonal = float(claimant["irrigated_demand_acres"]) * DEMAND_DUTY_AF_PER_ACRE
        for period_id, _, share in PERIOD_SPECS:
            demands.append(
                {
                    "period_id": period_id,
                    "claimant_id": claimant["claimant_id"],
                    "demand_af": round_float(seasonal * share, 6),
                    "demand_basis": "irrigated_nonfallow_WRLU_acres_x_assumed_2.0_net_af_per_acre_x_month_share",
                    "data_status": "derived_attributes_plus_assumed_duty_and_profile",
                }
            )

    terminal_parameters: list[dict[str, Any]] = []
    terminal_record_by_claimant = {row["claimant_id"]: row for row in claimant_terminals}
    for claimant_id, alpha in sorted(application_efficiency_by_claimant.items()):
        for period_id, _, _ in PERIOD_SPECS:
            terminal_parameters.append(
                {
                    "period_id": period_id,
                    "claimant_id": claimant_id,
                    "terminal_id": terminal_record_by_claimant[claimant_id]["terminal_id"],
                    "terminal_node": terminal_record_by_claimant[claimant_id]["terminal_node"],
                    "application_efficiency": round_float(alpha, 9),
                    "efficiency_basis": "irrigated_area_weighted_harmonic_mean_of_method_assumptions",
                    "data_status": "derived_from_WRLU_method_with_assumed_method_efficiencies",
                }
            )

    scenarios = SCENARIO_SPECS
    source_limits: list[dict[str, Any]] = []
    source_seasonal_limits: list[dict[str, Any]] = []
    total_days = sum(days for _, days, _ in PERIOD_SPECS)
    for scenario in scenarios:
        scenario_id = scenario["scenario_id"]
        for source in sources:
            factor = source_availability_factor(scenario_id, source)
            for period_id, days, _ in PERIOD_SPECS:
                q_af = float(source["design_envelope_cfs"]) * days * CFS_DAY_TO_AF * factor
                source_limits.append(
                    {
                        "scenario_id": scenario_id,
                        "period_id": period_id,
                        "source_id": source["source_id"],
                        "availability_factor": factor,
                        "q_af": round_float(q_af, 6),
                        "q_basis": "design_or_proxy_CFS_envelope_x_period_days_x_scenario_factor",
                        "data_status": "experimental_not_observed_2025_volume",
                    }
                )
            design_seasonal = float(source["design_envelope_cfs"]) * total_days * CFS_DAY_TO_AF
            if source["source_id"] == "s_15269":
                nominal_cap = min(design_seasonal, 18685.0)
                cap_basis = "published_Hyrum_Reservoir_capacity_18685_AF_used_as_release_ceiling"
                cap_status = "external_capacity_not_observed_2025_release"
            else:
                nominal_cap = design_seasonal
                cap_basis = "seasonal_sum_of_design_or_proxy_period_envelopes"
                cap_status = "derived_proxy_not_observed_2025_volume"
            source_seasonal_limits.append(
                {
                    "scenario_id": scenario_id,
                    "source_id": source["source_id"],
                    "seasonal_factor": factor,
                    "v_af": round_float(nominal_cap * factor, 6),
                    "v_basis": cap_basis,
                    "data_status": cap_status,
                }
            )

    edge_parameters: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_id = scenario["scenario_id"]
        for period_id, days, _ in PERIOD_SPECS:
            for edge in edges:
                if EDGE_SCENARIO_FACTORS is not None:
                    factor = float(
                        EDGE_SCENARIO_FACTORS.get(scenario_id, {}).get(edge["edge_id"], 1.0)
                    )
                else:
                    factor = 1.0
                    if scenario_id == "hyrum_canal_restriction_under_shortage" and edge["edge_id"] == "e_11819":
                        factor = 0.35
                capacity = float(edge["capacity_cfs_base"]) * days * CFS_DAY_TO_AF * factor
                edge_parameters.append(
                    {
                        "scenario_id": scenario_id,
                        "period_id": period_id,
                        "edge_id": edge["edge_id"],
                        "capacity_factor": factor,
                        "capacity_af": round_float(capacity, 6),
                        "efficiency": edge["efficiency_base"],
                        "capacity_status": edge["capacity_status"],
                        "efficiency_status": "assumed_not_calibrated",
                    }
                )

    source_groups: list[dict[str, Any]] = []
    source_group_members: list[dict[str, Any]] = []
    shared_source_limits: list[dict[str, Any]] = []
    for group_id, specification in SOURCE_GROUP_SPECS.items():
        source_design = sum(
            float(source["design_envelope_cfs"])
            for source in sources
            if source["source_id"] in specification["source_ids"]
        )
        terminal_ingress = sum(
            float(edge["capacity_cfs_base"])
            for edge in edges
            if edge["to_node"] in specification["terminal_nodes"]
        )
        base_envelope = min(source_design, terminal_ingress)
        source_groups.append(
            {
                "group_id": group_id,
                "group_label": specification["label"],
                "base_envelope_cfs": round_float(base_envelope, 6),
                "envelope_basis": "minimum_of_summed_source_design_and_terminal_ingress_capacity",
                "data_status": "derived_operational_envelope_not_observed_hydrologic_supply",
            }
        )
        for source_id_value in sorted(specification["source_ids"]):
            source_group_members.append(
                {"group_id": group_id, "source_id": source_id_value, "beta": 1.0}
            )
        for scenario in scenarios:
            scenario_id = scenario["scenario_id"]
            group_factor = GROUP_SCENARIO_FACTORS[scenario_id][group_id]
            for period_id, days, _ in PERIOD_SPECS:
                shared_source_limits.append(
                    {
                        "scenario_id": scenario_id,
                        "period_id": period_id,
                        "group_id": group_id,
                        "availability_factor": group_factor,
                        "w_af": round_float(base_envelope * days * CFS_DAY_TO_AF * group_factor, 6),
                        "w_basis": "derived_group_envelope_x_period_days_x_experimental_scenario_factor",
                        "data_status": "experimental_not_observed_2025_volume",
                    }
                )

    terminal_to_claimant = {row["terminal_node"]: row["claimant_id"] for row in claimant_terminals}
    source_role_names = dict(SOURCE_ROLE_NAMES)
    source_class_by_id = {row["source_id"]: row["source_class"] for row in sources}
    sources_per_claimant: dict[str, set[str]] = defaultdict(set)
    for row in paths:
        sources_per_claimant[terminal_to_claimant[row["terminal_node"]]].add(row["source_id"])
    source_roles: list[dict[str, Any]] = []
    for source_id_value, claimant_id in sorted(
        {(row["source_id"], terminal_to_claimant[row["terminal_node"]]) for row in paths}
    ):
        source_roles.append(
            {
                "source_id": source_id_value,
                "claimant_id": claimant_id,
                "operational_role": source_role_names.get(
                    (source_id_value, claimant_id),
                    _derived_source_role(
                        source_class_by_id[source_id_value],
                        len(sources_per_claimant[claimant_id]),
                    ),
                ),
                "role_basis": "observed_path_reachability_plus_claimant_specific_interpretation",
                "data_status": "derived_and_interpreted",
            }
        )

    seasonal_net_by_claimant: dict[str, float] = defaultdict(float)
    for row in demands:
        seasonal_net_by_claimant[row["claimant_id"]] += float(row["demand_af"])
    seasonal_gross_by_claimant = {
        claimant_id: net / application_efficiency_by_claimant[claimant_id]
        for claimant_id, net in seasonal_net_by_claimant.items()
    }
    terminal_nodes_by_claimant = {
        row["claimant_id"]: row["terminal_node"] for row in claimant_terminals
    }
    node_by_source = {row["source_id"]: row["node_id"] for row in sources}
    edge_by_id = {row["edge_id"]: row for row in edges}
    control_specs = [
        *(('source', source["source_id"], source["source_name"]) for source in sources),
        *(("edge", eid, label) for eid, label in EXTRA_CONTROL_EDGES if eid in edge_by_id),
    ]
    control_assets: list[dict[str, Any]] = []
    for resource_type, resource_id_value, label in control_specs:
        start = (
            node_by_source[resource_id_value]
            if resource_type == "source"
            else edge_by_id[resource_id_value]["to_node"]
        )
        reached = reachable_nodes(start, edges)
        reachable_claimants = sorted(
            claimant_id
            for claimant_id, terminal in terminal_nodes_by_claimant.items()
            if terminal in reached
        )
        normalization_scale = sum(seasonal_gross_by_claimant[item] for item in reachable_claimants)
        if normalization_scale <= 0:
            raise ValueError(f"Control {resource_type}/{resource_id_value} reaches no demand.")
        control_assets.append(
            {
                "control_asset_id": f"{resource_type}:{resource_id_value}",
                "resource_type": resource_type,
                "resource_id": resource_id_value,
                "control_label": label,
                "reachable_claimants": "|".join(reachable_claimants),
                "normalization_scale_af": round_float(normalization_scale, 6),
                "effort_coefficient": round_float(1.0 / normalization_scale, 12),
                "basis": "inverse_seasonal_gross_demand_reachable_from_control",
                "data_status": "experimental_normalization",
            }
        )

    landuse_summary_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    for parcel in parcels:
        key = (parcel["claimant_id"], parcel["crop_group"], parcel["irrigation_method"])
        summary = landuse_summary_map.setdefault(
            key,
            {
                "claimant_id": key[0],
                "crop_group": key[1],
                "irrigation_method": key[2],
                "polygon_count": 0,
                "acres": 0.0,
            },
        )
        summary["polygon_count"] += 1
        summary["acres"] += float(parcel["acres"])
    landuse_summary = sorted(
        (
            {**row, "acres": round_float(row["acres"], 6)}
            for row in landuse_summary_map.values()
        ),
        key=lambda row: (row["claimant_id"], row["crop_group"], row["irrigation_method"]),
    )

    measurement_stations = extract_measurement_stations({row["edge_id"] for row in edges})
    provenance = [
        {
            "source_id": "utah_distribution_network",
            "local_path": "DataSETs/Utah_Distribution_Network_2026",
            "official_url": "https://waterrights.utah.gov/gisinfo/DistributionNetwork.html",
            "snapshot_or_year": "snapshot 2026-08-25; selected edges valid in 2025",
            "benchmark_role": "nodes, physical flowlines, source-terminal paths, water-right labels, stations",
            "limitation": "live under-development layer; path connectors required; RelativeSize is only a proxy",
        },
        {
            "source_id": "utah_canals",
            "local_path": "DataSETs/Utah Canals/UDNR.WRT.Canals_CFS.csv",
            "official_url": "https://services.arcgis.com/ZzrwjTRez6FJiOq4/arcgis/rest/services/Utah_Canals/FeatureServer/0",
            "snapshot_or_year": "snapshot 2026-08-25; nonannual infrastructure layer",
            "benchmark_role": "MaxCFS for exact-name selected canal reaches",
            "limitation": "MaxCFS is incomplete statewide and is a design attribute, not observed monthly flow",
        },
        {
            "source_id": "irrigation_company_service_areas",
            "local_path": "DataSETs/Utah Irrigation Company Service Areas/utah_service_areas.geojson",
            "official_url": "https://services.arcgis.com/ZzrwjTRez6FJiOq4/arcgis/rest/services/Irrigation_Company_Service_Areas/FeatureServer/0",
            "snapshot_or_year": "snapshot 2026-08-25; nonannual living layer",
            "benchmark_role": "company identity, service polygons, company-to-terminal mapping",
            "limitation": "work-in-progress generalized polygons; not individual farmer boundaries",
        },
        {
            "source_id": "wrlu_2025",
            "local_path": "DataSETs/WaterRelatedLandUse_2025/*.gpkg",
            "official_url": "https://opendata.gis.utah.gov/datasets/utah-water-related-land-use/about",
            "snapshot_or_year": "SURV_YEAR=2025",
            "benchmark_role": "agricultural demand polygons, acres, crop group, irrigation method",
            "limitation": "centroid assignment does not clip parcel boundaries and supplies no farmer identity or water demand",
        },
        {
            "source_id": "hyrum_reservoir_capacity",
            "local_path": "not_embedded_external_report",
            "official_url": "https://water.utah.gov/wp-content/uploads/2024/12/WMSR-Appendix-2-Cache-Valley.pdf",
            "snapshot_or_year": "Utah water-management report accessed 2026-08",
            "benchmark_role": "18685 AF physical storage-capacity ceiling for Hyrum Reservoir",
            "limitation": "storage capacity is not observed 2025 release availability",
        },
    ]
    assumptions = [
        {
            "parameter": "demand_duty",
            "base_value": DEMAND_DUTY_AF_PER_ACRE,
            "unit": "net acre-foot/acre/May-Sep",
            "status": "assumed",
            "required_sensitivity": "1.5, 2.0, 2.5",
        },
        {
            "parameter": "monthly_demand_profile",
            "base_value": "0.12|0.22|0.28|0.24|0.14",
            "unit": "fraction for May|Jun|Jul|Aug|Sep",
            "status": "assumed",
            "required_sensitivity": "replace with calibrated ET or diversion profile",
        },
        {
            "parameter": "application_efficiency_by_method",
            "base_value": "Flood=0.60|Pivot=0.85|Sprinkler=0.75|Sub-irrigated=0.65|Wheel=0.78",
            "unit": "beneficial delivery/gross terminal withdrawal",
            "status": "assumed_from_method_class",
            "required_sensitivity": "multiply application-loss fraction by 0.5, 1.0 and 1.5",
        },
        {
            "parameter": "canal_loss_rate",
            "base_value": CANAL_LOSS_RATE_PER_KM,
            "unit": "exponential loss/km",
            "status": "assumed",
            "required_sensitivity": "0.0025, 0.005, 0.010",
        },
        {
            "parameter": "stream_loss_rate",
            "base_value": STREAM_LOSS_RATE_PER_KM,
            "unit": "exponential loss/km",
            "status": "assumed",
            "required_sensitivity": "0.0005, 0.001, 0.002",
        },
        {
            "parameter": "source_availability_and_outages",
            "base_value": "see scenarios.csv",
            "unit": "fraction of design/proxy envelope",
            "status": "experimental",
            "required_sensitivity": "factorial or one-at-a-time scenario sweep",
        },
        {
            "parameter": "recourse_budget",
            "base_value": "0|0.25|0.40|0.35|0.25",
            "unit": "normalized reconfiguration effort",
            "status": "experimental",
            "required_sensitivity": "scale contingency budgets by 0, 0.25, 0.5, 1 and 2",
        },
    ]
    sensitivity_cases: list[dict[str, Any]] = []
    case_number = 0
    for duty in (1.5, 2.0, 2.5):
        for loss_multiplier in (0.5, 1.0, 2.0):
            for source_scale in (0.8, 1.0, 1.2):
                for recourse_scale in (0.0, 0.25, 0.5, 1.0, 2.0):
                    case_number += 1
                    sensitivity_cases.append(
                        {
                            "case_id": f"factorial_{case_number:03d}",
                            "demand_duty_af_per_acre": duty,
                            "conveyance_loss_multiplier": loss_multiplier,
                            "source_limit_scale": source_scale,
                            "recourse_budget_scale": recourse_scale,
                            "is_base_case": (
                                duty == 2.0
                                and loss_multiplier == 1.0
                                and source_scale == 1.0
                                and recourse_scale == 1.0
                            ),
                        }
                    )

    payload: dict[str, Any] = {
        "schema_version": "cti-rlex-benchmark-v2",
        "benchmark_id": BENCHMARK_ID,
        "title": "Little Bear River Hyrum-Paradise-Highline 2025 data-informed benchmark",
        "benchmark_year": YEAR,
        "snapshot_date": "2026-08-25",
        "units": {"flow": "acre-foot per planning period", "capacity_source": "cfs", "area": "acre"},
        "scientific_scope": {
            "classification": "data-informed computational benchmark",
            "supports": "real path-based DAG routing, claimant-terminal aggregation, gross/net delivery, shared source envelopes, operational recourse and stress experiments",
            "does_not_validate": "individual-farmer fairness, observed 2025 source availability, or calibrated conveyance losses",
            "claimant_definition": "each F element is an irrigation-company service area, not an individual farmer",
        },
        "sets": {
            "periods": [row["period_id"] for row in periods],
            "scenarios": [row["scenario_id"] for row in scenarios],
            "nodes": [row["node_id"] for row in nodes],
            "edges": [row["edge_id"] for row in edges],
            "sources": [row["source_id"] for row in sources],
            "source_groups": [row["group_id"] for row in source_groups],
            "claimants": [row["claimant_id"] for row in claimants],
        },
        "periods": periods,
        "scenarios": scenarios,
        "nodes": nodes,
        "edges": edges,
        "sources": sources,
        "claimants": claimants,
        "claimant_terminals": claimant_terminals,
        "terminal_parameters": terminal_parameters,
        "paths": paths,
        "path_edges": path_edges,
        "parcels": parcels,
        "landuse_summary": landuse_summary,
        "demands": demands,
        "source_limits": source_limits,
        "source_seasonal_limits": source_seasonal_limits,
        "source_groups": source_groups,
        "source_group_members": source_group_members,
        "shared_source_limits": shared_source_limits,
        "source_roles": source_roles,
        "edge_parameters": edge_parameters,
        "control_assets": control_assets,
        "measurement_stations": measurement_stations,
        "provenance": provenance,
        "parameter_assumptions": assumptions,
        "sensitivity_cases": sensitivity_cases,
    }

    write_json(HERE / "benchmark.json", payload)
    report = validate_payload(payload)
    if TOPOLOGY_REDUCTION:
        # Only present when the path table needed an acyclic reduction, so benchmarks
        # whose connectors were already acyclic keep their previous validation report.
        report["topology_reduction"] = dict(TOPOLOGY_REDUCTION)
    report["per_claimant"] = {
        row["claimant_id"]: {
            "assigned_wrlu_polygons": row["assigned_wrlu_polygons"],
            "assigned_wrlu_acres": row["assigned_wrlu_acres"],
            "irrigated_demand_acres": row["irrigated_demand_acres"],
            "excluded_nonirrigated_acres": row["excluded_nonirrigated_acres"],
            "seasonal_net_demand_af": round_float(row["irrigated_demand_acres"] * DEMAND_DUTY_AF_PER_ACRE, 6),
            "application_efficiency": round_float(
                application_efficiency_by_claimant[row["claimant_id"]], 9
            ),
        }
        for row in claimants
    }
    report["input_data_status"] = {
        "observed_or_directly_joined": "network nodes/path relations; service-area identity; WRLU attributes; exact-name canal MaxCFS",
        "derived": "path connectors; WRLU centroid assignment; active irrigated area; application-efficiency aggregation; period volume conversion",
        "proxy": "Distribution Network RelativeSize where no exact MaxCFS join exists",
        "assumed_or_experimental": "demand duty/profile, conveyance and application efficiency, source/group derating, restrictions, control normalization and recourse budgets",
    }
    write_json(HERE / "validation_report.json", report)

    csv_specs: list[tuple[str, list[dict[str, Any]], list[str]]] = [
        ("periods.csv", periods, ["period_id", "sequence", "days", "seasonal_demand_share"]),
        ("scenarios.csv", scenarios, ["scenario_id", "label", "description", "recourse_budget", "probability_weight"]),
        ("nodes.csv", nodes, ["node_id", "source_node_id", "node_name", "node_type_code", "roles", "latitude", "longitude", "system_id", "pou_polygon_id"]),
        ("edges.csv", edges, ["edge_id", "source_record_id", "from_node", "to_node", "edge_role", "flowline_type", "flowline_name", "length_m", "capacity_cfs_base", "capacity_basis", "capacity_status", "efficiency_base", "efficiency_basis", "valid_in_2025"]),
        ("sources.csv", sources, ["source_id", "node_id", "source_name", "source_class", "design_envelope_cfs", "limit_basis", "limit_status"]),
        ("claimants.csv", claimants, ["claimant_id", "claimant_name", "claimant_kind", "individual_farmer_identity_available", "company_id", "service_polygon_objectid", "service_area_dataset_acres", "assigned_wrlu_acres", "irrigated_demand_acres", "excluded_nonirrigated_acres", "assigned_wrlu_polygons", "water_rights_text", "measurement_station_ids", "county", "basin", "subarea"]),
        ("claimant_terminals.csv", claimant_terminals, ["terminal_id", "claimant_id", "terminal_node", "terminal_share", "mapping_basis", "mapping_status"]),
        ("terminal_parameters.csv", terminal_parameters, ["period_id", "claimant_id", "terminal_id", "terminal_node", "application_efficiency", "efficiency_basis", "data_status"]),
        ("paths.csv", paths, ["path_id", "source_id", "source_node", "terminal_node", "water_right_number", "path_type", "valid_in_2025"]),
        ("path_edges.csv", path_edges, ["path_id", "sequence", "edge_id", "relation", "source_node", "terminal_node", "water_right_number"]),
        ("parcels.csv", parcels, ["claimant_id", "wrlu_objectid", "landuse", "crop_group", "description", "irrigation_method", "acres", "survey_year", "county", "basin", "subarea", "centroid_x_epsg26912", "centroid_y_epsg26912", "assignment_method", "assignment_candidate_count"]),
        ("landuse_summary.csv", landuse_summary, ["claimant_id", "crop_group", "irrigation_method", "polygon_count", "acres"]),
        ("demands.csv", demands, ["period_id", "claimant_id", "demand_af", "demand_basis", "data_status"]),
        ("source_limits.csv", source_limits, ["scenario_id", "period_id", "source_id", "availability_factor", "q_af", "q_basis", "data_status"]),
        ("source_seasonal_limits.csv", source_seasonal_limits, ["scenario_id", "source_id", "seasonal_factor", "v_af", "v_basis", "data_status"]),
        ("source_groups.csv", source_groups, ["group_id", "group_label", "base_envelope_cfs", "envelope_basis", "data_status"]),
        ("source_group_members.csv", source_group_members, ["group_id", "source_id", "beta"]),
        ("shared_source_limits.csv", shared_source_limits, ["scenario_id", "period_id", "group_id", "availability_factor", "w_af", "w_basis", "data_status"]),
        ("source_roles.csv", source_roles, ["source_id", "claimant_id", "operational_role", "role_basis", "data_status"]),
        ("edge_parameters.csv", edge_parameters, ["scenario_id", "period_id", "edge_id", "capacity_factor", "capacity_af", "efficiency", "capacity_status", "efficiency_status"]),
        ("control_assets.csv", control_assets, ["control_asset_id", "resource_type", "resource_id", "control_label", "reachable_claimants", "normalization_scale_af", "effort_coefficient", "basis", "data_status"]),
        ("measurement_stations.csv", measurement_stations, ["station_id", "station_name", "linked_edge_id", "flowline_record_id", "status", "units", "latitude", "longitude", "url_2025", "use_in_v1", "note"]),
        ("provenance.csv", provenance, ["source_id", "local_path", "official_url", "snapshot_or_year", "benchmark_role", "limitation"]),
        ("parameter_assumptions.csv", assumptions, ["parameter", "base_value", "unit", "status", "required_sensitivity"]),
        ("sensitivity_cases.csv", sensitivity_cases, ["case_id", "demand_duty_af_per_acre", "conveyance_loss_multiplier", "source_limit_scale", "recourse_budget_scale", "is_base_case"]),
    ]
    stale = OUT / "effort_coefficients.csv"
    if stale.exists():
        stale.unlink()
    for filename, rows, fields in csv_specs:
        write_csv(OUT / filename, rows, fields)

    checksum_targets = [HERE / "benchmark.json", HERE / "validation_report.json"] + sorted(OUT.glob("*.csv"))
    with (HERE / "checksums_sha256.txt").open("w", encoding="utf-8", newline="\n") as stream:
        for path in checksum_targets:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            stream.write(f"{digest}  {path.relative_to(HERE).as_posix()}\n")
    return report


def main() -> None:
    report = build()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
