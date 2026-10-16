# Little Bear River at Paradise, Utah: monthly mean discharge, USGS 10105900

The monthly mean discharge, in cubic feet per second, of the U.S. Geological Survey gauge
10105900, Little Bear River at Paradise, Utah, from October 1992 to April 2026, as the USGS
statistics service delivered it. The benchmarks do not read this file.
`scripts/historical_reliability.py` uses the months May to September of 1993 to 2025, the 33
seasons the record holds in full, as an index of how wet or dry each year was on the Little
Bear River, and tests the three-claimant instance against those years (Reviewer 1, point 1.2).

Files:

- `10105900_monthly_mean_discharge.rdb`: the service's tab-separated RDB file, unchanged.
  Columns `year_nu`, `month_nu` and `mean_va` carry the year, the month and the mean of the
  daily mean discharges of that month. The service computes the statistics from approved
  daily values.
- `provenance.json`: the request, the retrieval time the file records, the months it covers
  and its SHA-256.

How the script uses it: for each month the ratio of the month's mean to the median of that
month over 1993 to 2025, capped at 1, scales the limits of the direct diversions and the
shared subsystem envelopes; the ratio of the year's May-to-September volume to the median of
those volumes over 1993 to 2025, capped at 1, scales the seasonal volume of each reservoir. One gauge stands for the whole
system: the scaling is an index of dryness, not a flow routed to each diversion.
