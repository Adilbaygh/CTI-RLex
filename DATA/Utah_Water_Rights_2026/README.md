# Water rights named in the benchmarks, Utah Division of Water Rights, 2026

The points of diversion, from the Utah Division of Water Rights' Utah Points of Diversion layer
(WRPOD), of every water right that the two released benchmarks name: in a claimant's
water-rights text (`claimants.csv`, `water_rights_text`) or on an official path
(`paths.csv`, `water_right_number`). The benchmarks do not read this file. The priority
comparator `scripts/prior_lex.py` takes from it the priority date, flow and source of the
decreed rights on each claimant's paths (Reviewer 1, point 2.1).

Files:

- `points_of_diversion.csv`: 247 points of 61 water rights, one row per point of diversion,
  with every column of the layer as `scripts/fetch_wrpod.py` downloaded it, the point's
  longitude and latitude, and that script's two selection flags. A right with several points
  has one row per point; its priority date and flow repeat on each. `PRIORITY` is the
  priority date as YYYYMMDD (a decree may give the year alone), `CFS` the flow in cubic feet
  per second, `TYPE_OF_RIGHT` the kind of record (`Decree`, `Application To Appropriate`,
  `Adverse Use`). The field definitions are at https://waterrights.utah.gov/gisinfo/wrpod.htm.
- `provenance.json`: the layer, its last edit date, the retrieval time, the SHA-256 of the
  full snapshot the rows were copied from and of this file, the rights each benchmark names,
  and the two it names that the layer does not contain.

The rows were copied unchanged from the snapshot of 2026-10-11 (layer last edited
2026-10-10) by `scripts/extract_water_rights.py`, which checks the snapshot against its
recorded checksum first. The Division regenerates the layer every day, so a new download can
differ; the checksums identify the snapshot used.

Two named rights are Idaho rights and are not in the Utah layer: `ID 13-2066` (Cub River
Irrigation Co.) and `ID 13-974` (West Cache Irrigation Co.).
