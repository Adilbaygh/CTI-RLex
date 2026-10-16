# Observed canal flows, Little Bear River claimants, 2025

River Commissioner records of the Utah Division of Water Rights for the five measuring
stations that the Little Bear River benchmark lists for its three claimants
(`../LittleBearRiver_2025_Benchmark/benchmark.json`, table `measurement_stations`). The
benchmark does not read these files. `scripts/station_comparison.py` sets them against the
benchmark's nominal flows and writes `results/station_comparison.json` (Reviewer 1, point 2.2).

| Station | Name | Claimant | Benchmark reach | Measuring device | Rating |
|---|---|---|---|---|---|
| 2771 | Hyrum Canal at Osmonds | Hyrum Irrigation Co. | `e_3554` | 4 ft Parshall flume | Fair |
| 2772 | Little Feeder | Hyrum Irrigation Co. | none | ultrasonic meter | Unrated |
| 2776 | Paradise Canal | Paradise Irrigation Co. | `e_10136` | 4 ft Parshall flume | Unrated |
| 9738 | Paradise Canal below Black Tube | Paradise Irrigation Co. | `e_10136` | 4 ft Parshall flume | Unrated |
| 9739 | Highline Canal below Weeks Farm | Porcupine Highline Canal Co. | `e_13081` | Greyline AVFM 5.0 | Unrated |

Files:

- `dailydata-<station>-2025-2025.csv`: mean daily discharge in cubic feet per second for
  2025, exactly as the DVRTVIEW viewer delivered it (Daily Comma Delimited Data, Beginning and
  End Year 2025, Open Spreadsheet). A day without a record has no row.
- `monthly-summary-<station>.txt`: the viewer's Monthly Summary Table for the station's whole
  record, in acre-feet: the text of the report, with trailing spaces removed. Each month is the
  sum of the days that carry a record.
- `provenance.json`: source, retrieval date, the station details from the viewer's Station
  Information pages, the benchmark reach and claimant of each station, and the SHA-256 of each
  daily file.

Retrieved on 2026-10-11. The viewer does not mark the 2025 values as approved or
provisional. The state's HydroServer labels the datastreams of stations 2771, 9738 and 9739
provisional.

Stations 2776 and 9738 lie about two metres apart on the same canal. From May to September
2025 their monthly volumes differ by up to 27%, so the comparison reports them side by side
and never adds them.
