"""Download the Utah points of diversion that the priority comparator needs (Reviewer 1, point 2.1).

A reviewer asked how the allocation rules relate to prior appropriation, the doctrine that
actually governs Utah water. Comparing CTI-RLex with a priority-ordered rule needs the priority
date of every water right behind every claimant, and those dates are kept by the Utah Division
of Water Rights in its points-of-diversion database (WRPOD). The Division publishes that
database as a point layer generated daily, "Utah Points of Diversion", through its ArcGIS
feature service; the field definitions are in the WRPOD metadata,
https://waterrights.utah.gov/gisinfo/wrpod.htm.

This script takes two selections from that layer and writes them to one file:

  * every point of diversion inside the study area, a latitude-longitude box around Cache
    County with a margin, so that rights can also be matched by owner and by source;
  * every point of diversion of a water right the two released benchmarks name -- in a
    claimant's water-rights text or on an official path -- wherever it lies.

Each row keeps every attribute of the layer, the point's longitude and latitude, and two flags
saying which selection it came from. A provenance file records the service, the layer's last
edit date, the retrieval time, the selection, the rights the benchmarks name but the layer does
not contain, and the SHA-256 of the data file, because the layer is regenerated every day and
a rerun on another day may return different rows.

Only the Python standard library is used. The layer is read in pages of at most 2000 records,
the service's limit, ordered by OBJECTID.

Run:  python scripts/fetch_wrpod.py [--output-dir DIR]
      DIR defaults to LEXIMIN_DATASETS/Utah_Points_of_Diversion (LEXIMIN_DATASETS as for the
      benchmark generators: the root that holds the open Utah layers).
Writes: utah_points_of_diversion_cache_county.csv and utah_points_of_diversion_provenance.json
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATASETS = Path(os.environ.get("LEXIMIN_DATASETS", str(REPO / "DataSETs")))
BENCHMARKS = (
    REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
)

SERVICE = "https://services.arcgis.com/ZzrwjTRez6FJiOq4/arcgis/rest/services/Utah_Points_of_Diversion/FeatureServer/0"
ITEM = "https://www.arcgis.com/home/item.html?id=7bf556ebe3bc4362ab07d8945332c940"
METADATA = "https://waterrights.utah.gov/gisinfo/wrpod.htm"

# Cache County, Utah, with a margin of about five kilometres: west, south, east, north (WGS 84).
STUDY_AREA = (-112.25, 41.30, -111.30, 42.05)
PAGE = 2000             # the service's maxRecordCount
NAMES_PER_QUERY = 150   # water-right numbers per IN clause
TIMEOUT = 120           # seconds per request
RETRIES = 4
USER_AGENT = "CTI-RLex benchmark tools (research use; https://github.com/Adilbaygh/CTI-RLex)"

DATA_FILE = "utah_points_of_diversion_cache_county.csv"
PROVENANCE_FILE = "utah_points_of_diversion_provenance.json"


def request(url: str, parameters: dict[str, str]) -> dict:
    """POST one query and return the decoded JSON, retrying transient failures."""

    body = urllib.parse.urlencode(parameters).encode("utf-8")
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            call = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(call, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if "error" in payload:
                raise RuntimeError(f"service error: {payload['error']}")
            return payload
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as error:
            last = error
            time.sleep(2 ** attempt)
    raise SystemExit(f"could not query {url}: {last}")


def layer_description() -> dict:
    return request(SERVICE, {"f": "json"})


def query_all(where: str, *, envelope: tuple[float, float, float, float] | None = None) -> list[dict]:
    """Every feature matching ``where`` (and the envelope), page by page."""

    rows: list[dict] = []
    offset = 0
    while True:
        parameters = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "orderByFields": "OBJECTID ASC",
            "resultOffset": str(offset),
            "resultRecordCount": str(PAGE),
            "f": "json",
        }
        if envelope is not None:
            parameters.update({
                "geometry": ",".join(str(value) for value in envelope),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            })
        payload = request(f"{SERVICE}/query", parameters)
        features = payload.get("features", [])
        for feature in features:
            row = dict(feature["attributes"])
            geometry = feature.get("geometry") or {}
            row["longitude"] = geometry.get("x")
            row["latitude"] = geometry.get("y")
            rows.append(row)
        offset += len(features)
        if not features or (len(features) < PAGE and not payload.get("exceededTransferLimit")):
            return rows


def count(where: str, *, envelope: tuple[float, float, float, float] | None = None) -> int:
    parameters = {"where": where, "returnCountOnly": "true", "f": "json"}
    if envelope is not None:
        parameters.update({
            "geometry": ",".join(str(value) for value in envelope),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        })
    return int(request(f"{SERVICE}/query", parameters)["count"])


def expand(text: str) -> list[str]:
    """Water-right numbers in a text such as '25-1719 to 25-1724, 25-2037'."""

    numbers: list[str] = []
    for part in re.split(r"[,;]", text or ""):
        part = part.strip()
        span = re.fullmatch(r"(\d+)-(\d+)\s+to\s+(\d+)-(\d+)", part)
        if span and span.group(1) == span.group(3) and int(span.group(2)) <= int(span.group(4)):
            area = span.group(1)
            numbers.extend(f"{area}-{number}" for number in range(int(span.group(2)), int(span.group(4)) + 1))
            continue
        numbers.extend(re.findall(r"\b\d+-\d+[A-Z]?\b", part))
    return numbers


def named_rights() -> dict[str, list[str]]:
    """Every water right a released benchmark names, with where it is named."""

    named: dict[str, set[str]] = {}
    for path in BENCHMARKS:
        payload = json.loads(path.read_text(encoding="utf-8"))
        benchmark = payload["benchmark_id"]
        for claimant in payload["claimants"]:
            for number in expand(claimant.get("water_rights_text", "")):
                named.setdefault(number, set()).add(f"{benchmark}:claimant:{claimant['claimant_id']}")
        for route in payload["paths"]:
            number = (route.get("water_right_number") or "").strip()
            if number:
                named.setdefault(number, set()).add(f"{benchmark}:path:{route['path_id']}")
    return {number: sorted(places) for number, places in sorted(named.items())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output-dir", type=Path, default=DATASETS / "Utah_Points_of_Diversion")
    arguments = parser.parse_args()
    output = arguments.output_dir
    output.mkdir(parents=True, exist_ok=True)

    description = layer_description()
    fields = [field["name"] for field in description["fields"]]
    last_edit = description.get("editingInfo", {}).get("dataLastEditDate")
    retrieved = dt.datetime.now(dt.timezone.utc)

    expected = count("1=1", envelope=STUDY_AREA)
    in_area = query_all("1=1", envelope=STUDY_AREA)
    if len(in_area) != expected:
        raise SystemExit(f"study area: the service counts {expected} points but {len(in_area)} were returned")
    print(f"study area {STUDY_AREA}: {len(in_area)} points of diversion")

    rights = named_rights()
    numbers = list(rights)
    named_rows: list[dict] = []
    for start in range(0, len(numbers), NAMES_PER_QUERY):
        chunk = numbers[start:start + NAMES_PER_QUERY]
        where = "WRNUM IN (" + ",".join("'" + number.replace("'", "''") + "'" for number in chunk) + ")"
        named_rows.extend(query_all(where))
    found = {row["WRNUM"] for row in named_rows}
    missing = [number for number in numbers if number not in found]
    print(f"rights named in the benchmarks: {len(numbers)}; points of diversion found for "
          f"{len(found)}; not in the layer: {missing or 'none'}")

    merged: dict[int, dict] = {}
    for row in in_area:
        merged[row["OBJECTID"]] = {**row, "in_study_area": True, "named_in_benchmark": False}
    for row in named_rows:
        entry = merged.setdefault(row["OBJECTID"], {**row, "in_study_area": False, "named_in_benchmark": False})
        entry["named_in_benchmark"] = True
    columns = fields + ["longitude", "latitude", "in_study_area", "named_in_benchmark"]

    data_path = output / DATA_FILE
    with data_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for objectid in sorted(merged):
            writer.writerow(merged[objectid])
    digest = hashlib.sha256(data_path.read_bytes()).hexdigest()

    provenance = {
        "dataset": "Utah Points of Diversion (WRPOD), Utah Division of Water Rights",
        "service": SERVICE,
        "item": ITEM,
        "field_definitions": METADATA,
        "note": "The Division regenerates the layer daily from its water-right database; a rerun on "
                "another day can return different rows, so this record and the checksum identify the "
                "snapshot used.",
        "layer_data_last_edit_utc": (
            dt.datetime.fromtimestamp(last_edit / 1000, dt.timezone.utc).isoformat() if last_edit else None
        ),
        "retrieved_utc": retrieved.isoformat(timespec="seconds"),
        "study_area_wgs84_west_south_east_north": list(STUDY_AREA),
        "points_in_study_area": len(in_area),
        "rights_named_in_the_benchmarks": rights,
        "named_rights_with_points": sorted(found),
        "named_rights_not_in_the_layer": missing,
        "points_of_named_rights": len(named_rows),
        "points_of_named_rights_outside_the_study_area": sum(
            1 for row in merged.values() if row["named_in_benchmark"] and not row["in_study_area"]
        ),
        "rows": len(merged),
        "columns": columns,
        "data_file": DATA_FILE,
        "sha256": digest,
    }
    (output / PROVENANCE_FILE).write_text(
        json.dumps(provenance, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {data_path} ({len(merged)} rows, sha256 {digest[:12]}...) and {output / PROVENANCE_FILE}")


if __name__ == "__main__":
    sys.exit(main())
