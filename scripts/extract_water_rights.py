"""Copy into the repository the points of diversion of the water rights the benchmarks name
(Reviewer 1, point 2.1).

scripts/fetch_wrpod.py downloads the Utah Points of Diversion layer (WRPOD) of the Utah Division
of Water Rights to the open-data root, outside the repository: every point of diversion in and
around Cache County, about 8 MB, from a layer the Division regenerates every day. The priority
comparator (scripts/prior_lex.py) needs only the points of the water rights that the two released
benchmarks name, in a claimant's water-rights text or on an official path; fetch_wrpod.py flags
those rows named_in_benchmark. This script checks the downloaded snapshot against the SHA-256
its provenance file records, and copies the flagged rows with every column, unchanged, into
DATA/Utah_Water_Rights_2026, so that the comparator runs for a reader who has the repository
alone. The provenance of the copy names the snapshot it came from.

Only the Python standard library is used.

Run:  python scripts/extract_water_rights.py [--snapshot-dir DIR]
      DIR defaults to LEXIMIN_DATASETS/Utah_Points_of_Diversion, as in fetch_wrpod.py.
Writes: DATA/Utah_Water_Rights_2026/points_of_diversion.csv and provenance.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATASETS = Path(os.environ.get("LEXIMIN_DATASETS", str(REPO / "DataSETs")))
SNAPSHOT_FILE = "utah_points_of_diversion_cache_county.csv"
SNAPSHOT_PROVENANCE = "utah_points_of_diversion_provenance.json"
OUTPUT = REPO / "DATA" / "Utah_Water_Rights_2026"
DATA_FILE = "points_of_diversion.csv"
PROVENANCE_FILE = "provenance.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--snapshot-dir", type=Path, default=DATASETS / "Utah_Points_of_Diversion")
    arguments = parser.parse_args()
    snapshot = arguments.snapshot_dir / SNAPSHOT_FILE
    record = json.loads((arguments.snapshot_dir / SNAPSHOT_PROVENANCE).read_text(encoding="utf-8"))

    raw = snapshot.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != record["sha256"]:
        raise SystemExit(
            f"{snapshot} has SHA-256 {digest}, but its provenance records {record['sha256']}: "
            "the file is not the snapshot the provenance describes"
        )

    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""))
    columns = list(reader.fieldnames or [])
    named = [row for row in reader if row["named_in_benchmark"] == "True"]
    if len(named) != record["points_of_named_rights"]:
        raise SystemExit(
            f"{len(named)} rows are flagged named_in_benchmark, but the provenance records "
            f"{record['points_of_named_rights']}"
        )

    # The same writer settings as fetch_wrpod.py, so that every row is the snapshot's own line.
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(named)
    text = buffer.getvalue()
    source_lines = set(raw.decode("utf-8").split("\n"))
    changed = [line for line in text.split("\n") if line and line not in source_lines]
    if changed:
        raise SystemExit(f"{len(changed)} copied rows differ from their line in the snapshot")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    data_path = OUTPUT / DATA_FILE
    data_path.write_bytes(text.encode("utf-8"))

    rights = sorted({row["WRNUM"] for row in named})
    provenance = {
        "dataset": record["dataset"],
        "service": record["service"],
        "item": record["item"],
        "field_definitions": record["field_definitions"],
        "layer_data_last_edit_utc": record["layer_data_last_edit_utc"],
        "retrieved_utc": record["retrieved_utc"],
        "snapshot_file": SNAPSHOT_FILE,
        "snapshot_rows": record["rows"],
        "snapshot_sha256": record["sha256"],
        "selection": (
            "the rows of the snapshot whose named_in_benchmark flag is True: every point of "
            "diversion of a water right that a claimant's water-rights text or an official path "
            "of either released benchmark names, wherever the point lies"
        ),
        "rights_named_in_the_benchmarks": record["rights_named_in_the_benchmarks"],
        "named_rights_not_in_the_layer": record["named_rights_not_in_the_layer"],
        "rights_with_points": rights,
        "rows": len(named),
        "columns": columns,
        "data_file": DATA_FILE,
        "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "written_by": "scripts/extract_water_rights.py",
    }
    (OUTPUT / PROVENANCE_FILE).write_text(
        json.dumps(provenance, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"wrote {data_path} ({len(named)} points of {len(rights)} water rights, sha256 "
        f"{provenance['sha256'][:12]}...) from the snapshot of {record['retrieved_utc']}"
    )


if __name__ == "__main__":
    sys.exit(main())
