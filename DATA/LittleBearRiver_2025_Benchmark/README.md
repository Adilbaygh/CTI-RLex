# Little Bear River 2025 CTI-RLex benchmark

This directory contains a reproducible, data-informed benchmark for the CTI-RLex model.
The model is defined in the accompanying article and its schema is documented in
`DATA/benchmarks_dag/SCHEMA_DAG.md`. It represents selected Hyrum, Paradise and Porcupine
Highline distribution paths in Cache Valley, Utah. The canonical input is
`benchmark.json`; normalized CSV tables contain the same inputs for Python, R, GIS and
supplementary-material workflows.

## Benchmark at a glance

| Model object | Benchmark v2 realization |
|---|---|
| `G=(V,E)` | 21 nodes; 14 official physical reaches; 5 labelled path-table connectors |
| hydraulic components | 2 weakly connected subsystems: Hyrum and Paradise-Highline |
| `S` | 4 injections: 2 surface diversions and 2 reservoir releases |
| `H` | 2 shared operational source groups |
| `F` | 3 irrigation-company service-area claimants, not individual farmers |
| `T_f` | one terminal record per selected claimant; terminal IDs are explicit and splittable for tests |
| `K` | May--September 2025, five monthly periods |
| `Omega` | nominal plus four non-identical shortage/restriction scenarios |
| `d` | 4,322.545920 active irrigated acres and 8,645.091840 AF derived seasonal net demand |
| excluded area | 86.148646 acres labelled Dry Crop or Fallow/Idle; retained for provenance, excluded from demand |
| `alpha` | claimant application efficiencies 0.669133, 0.758318 and 0.779046 |
| `Q,V,W` | period source limits, seasonal source caps and shared subsystem envelopes |
| `C,eta` | period edge capacities and assumed length-decay conveyance efficiencies |
| `A` | 7 controls: 4 source setpoints and 3 physical branch/head gates |
| sensitivity | 135 full-factorial duty/loss/supply/recourse cases |

All structural and completeness checks pass; see `validation_report.json`.

## Scientific classification

This is a **data-informed computational benchmark**, not a calibrated 2025 digital twin
or an observed allocation record. It supports reproducible routing, gross/net accounting,
multi-source response, shared-envelope constraints, scenario sensitivity, algorithm
comparison and company-service-area equity. It cannot validate individual-farmer equity
because the open layers do not contain farmer identity or a verified farmer-to-turnout
map.

The two weakly connected subsystems are explicitly reported. The benchmark must not be
described as one hydraulically connected allocation network. Joint CTI-RLex optimization
is a portfolio experiment across the two systems; direct competition occurs within each
source group, including competition between the Paradise and Highline claimants.

## Evidence, derivation and assumptions

| Input | Status | Construction |
|---|---|---|
| nodes, reaches and 12 source-terminal paths | direct selection | Utah Water Right Distribution Network |
| 5 logical connectors | derived | repair gaps in official path relations; excluded from control assets |
| company-terminal map | direct company-level match | path endpoint, terminal name and service-area identity |
| WRLU crop/method/acres | direct 2025 attributes | polygon centroid assigned to one selected service polygon |
| active demand area | deterministic filter | Dry Crop and Fallow/Idle excluded; all rows retained in parcel tables |
| net demand `d` | derived with assumptions | active acres x 2.0 net AF/acre x monthly shares |
| application efficiency `alpha` | derived with assumptions | area-weighted harmonic mean of method efficiencies |
| reach capacity, tier 1 (7 reaches here) | observed design attribute | exact-name join to Utah Canals `MaxCFS` |
| reach capacity, tier 2 (7 reaches here) | proxy | Distribution Network `RelativeSize` treated as CFS pending calibration |
| reach capacity, tier 3 (0 reaches here) | derived | minimum known capacity of the paths that traverse the reach; used only where neither an exact-name `MaxCFS` join nor a `RelativeSize` attribute exists |
| connector capacities | derived | minimum adjacent path capacity |
| conveyance efficiency `eta` | assumed | exponential length decay; connectors are lossless |
| period source limit `Q` | experimental envelope | source design/proxy CFS x days x scenario factor |
| seasonal source limit `V` | external/derived ceiling | Hyrum storage capacity where available; otherwise summed design envelope |
| shared limit `W` | derived plus experimental derating | minimum of summed source design and terminal-ingress capacity x scenario factor |
| control effort and budget | experimental | only source setpoints and selected physical gates; normalized by reachable gross demand |

Reach capacity evidence is assigned in three declared tiers, in order. Tier 3 exists
because a small number of officially named reaches in the wider Cache Valley selection
carry neither an exact-name `MaxCFS` join nor a `RelativeSize` attribute; it applies the
same conservative rule already used for derived path connectors. **No reach in this
instance falls into tier 3**, so every capacity here is either observed or a
`RelativeSize` proxy, exactly as in the previously published build.

The common crop duty and monthly profile are not calibrated ET. Irrigation method affects
gross/net conversion, but crop-specific ET is not inferred without a defensible local
calibration. Every table labels observations, derivations, proxies and assumptions.

## Scenario set

| Scenario | Purpose |
|---|---|
| `nominal` | design-envelope reference |
| `moderate_system_shortage` | moderate shared-system and source derating |
| `severe_system_shortage` | low shared envelopes with higher permitted recourse |
| `paradise_diversion_outage_under_shortage` | local Paradise source disabled while the Porcupine route remains |
| `hyrum_canal_restriction_under_shortage` | partial Hyrum Canal restriction plus local source derating |

Every terminal remains reachable from at least one active source in every
scenario-period. Scenario factors and recourse budgets are experiment design parameters,
not probabilities or observations. Contingency weights sum to one and are used only in a
secondary tie-break after the complete robust guarantee vector is fixed.

## Main files

- `benchmark.json` — canonical CTI-RLex input;
- `validation_report.json` — DAG, coverage, gross/net and scientific-scope audit;
- `checksums_sha256.txt` — SHA-256 integrity hashes;
- `generate_benchmark.py` and `validate_benchmark.py` — deterministic build and
  dependency-free validation;
- `generate_cache_valley_benchmark.py` — the county-scale driver that builds the
  ten-claimant instance in `../CacheValley_2025_Benchmark/` from the same open layers,
  under the same schema and selection rules. Its own source was lost and only a stale
  Python 3.10 bytecode of an earlier revision survived; the file shipped here is
  reconstructed from that bytecode, and wherever the two disagree the released records
  decide. It rebuilds the released instance byte for byte, so the determinism check below
  now covers both instances. The acyclicity repair it applies is the
  `acyclic_connector_selection` routine in `generate_benchmark.py`: candidates are ordered
  by decreasing number of dependent candidate paths, then by increasing tail-node
  identifier, then by increasing head-node identifier, and each is accepted only while the
  graph stays acyclic. The full ordered decision record for all 41 candidates — position,
  connector, endpoints, dependent candidate paths, decision and reason — is published in
  `../CacheValley_2025_Benchmark/discovery_summary.json` under `connector_decisions`, so
  the reduction can be audited or replayed under a different repair rule;
- `little_bear_river_2025_benchmark_map.png` and `.svg` — publication map;
- `data/claimants.csv`, `claimant_terminals.csv`, `terminal_parameters.csv` — claimant,
  terminal-record and application-efficiency inputs;
- `data/sources.csv`, `source_limits.csv`, `source_seasonal_limits.csv` — source type,
  `Q` and `V`;
- `data/source_groups.csv`, `source_group_members.csv`, `shared_source_limits.csv` —
  group membership and `W`;
- `data/source_roles.csv` — claimant-specific routine/supplemental source role;
- `data/edges.csv`, `edge_parameters.csv` — topology, `C` and `eta`;
- `data/control_assets.csv`, `scenarios.csv` — bounded recourse inputs;
- `data/parcels.csv`, `landuse_summary.csv`, `demands.csv` — WRLU provenance and `d`;
- `data/sensitivity_cases.csv` — 135 full-factorial cases;
- `data/provenance.csv`, `parameter_assumptions.csv` — source and assumption register.

## Rebuild, solve and verify

Run from the repository root:

The open-data root defaults to `DataSETs/` beside the repository. Set
`LEXIMIN_DATASETS` when the layers live elsewhere:

```powershell
$env:LEXIMIN_DATASETS = "C:\DataSETs"
python -B DATA\LittleBearRiver_2025_Benchmark\generate_benchmark.py
python -B DATA\LittleBearRiver_2025_Benchmark\validate_benchmark.py
python -B DATA\LittleBearRiver_2025_Benchmark\plot_benchmark_map.py
$env:PYTHONPATH = "src"
python -B scripts\run_cti_rlex.py `
  DATA\LittleBearRiver_2025_Benchmark\benchmark.json `
  --output results\cti_rlex_base.json
python -B -m pytest
```

The base run gives period-wise robust guarantees of approximately 0.447698 for
`company_088` and 0.419511 for `company_130` and `company_132`. Maximum LP residuals
are below `4e-13`, and splitting the Paradise terminal record into four records changes
the guarantee vector by about `1.1e-16`. These are numerical verification results, not
field-performance claims.

### Rebuilding the ten-claimant instance

The county instance takes two passes. The acyclicity repair can leave a service area with
no route at all, and which areas those are is known only after the repair has run — but the
shared source groups are derived from the claimant set, so they have to be derived from the
survivors. The first pass therefore stops as soon as the repair reports them, before any
benchmark file is written, and leaves `unrouted_claimants.json` behind; the second rebuilds
with the survivors as claimants while keeping the first pass's path set, so the repair sees
the same candidate connectors and settles on the same graph:

```powershell
$env:LEXIMIN_DATASETS = "C:\DataSETs"
python -B scripts\rebuild_cache_valley.py
```

Of the sixteen discovered service areas one carries no irrigated WRLU acreage and five lose
every route to the repair, which is how the instance arrives at ten claimants, seven shared
subsystems and thirty-one paths. The expensive county-wide discovery pass over the raw
layers is served from the published `selection.json`, which the rebuild only reads, so the
two passes take minutes rather than hours and reproduce `benchmark.json` byte for byte.
Each of those is checkable from the published records alone: `checksums_sha256.txt` carries
the checksum, `discovery_summary.json` the ordered decision record for all 41 connector
candidates, and the `control_assets` block of `benchmark.json` the ten head gates.

### Build determinism

`generate_benchmark.py` is deterministic: rebuilding from unchanged input layers
reproduces every file byte for byte, so `checksums_sha256.txt` is a regression test for
the generator itself. Any change to the generator must leave this file unchanged unless
the change is intended to alter the benchmark, in which case the new hashes and the
reason belong in the same commit.

## Source datasets

- [Utah Water Right Distribution Network](https://waterrights.utah.gov/gisinfo/DistributionNetwork.html)
- [Utah Canals feature service](https://services.arcgis.com/ZzrwjTRez6FJiOq4/arcgis/rest/services/Utah_Canals/FeatureServer/0)
- [Irrigation Company Service Areas](https://services.arcgis.com/ZzrwjTRez6FJiOq4/arcgis/rest/services/Irrigation_Company_Service_Areas/FeatureServer/0)
- [Utah Water-Related Land Use](https://opendata.gis.utah.gov/datasets/utah-water-related-land-use/about)
- [Utah water-management report containing the Hyrum capacity value](https://water.utah.gov/wp-content/uploads/2024/12/WMSR-Appendix-2-Cache-Valley.pdf)

Before journal submission, replace proxy capacities, assumed efficiencies and scenario
envelopes with local calibration data if available. Individual-farmer claims additionally
require a documented farmer-ID--terminal map.
