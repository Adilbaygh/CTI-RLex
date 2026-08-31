# CTI-RLex

CTI-RLex is an open-source research tool for claimant-centred lexicographic fair water
allocation under scarcity on lossy, capacity-constrained, multi-source irrigation
networks.

The software combines a reusable optimization library with a desktop benchmark
analyzer. Every displayed result is computed from the benchmark selected by the user;
the application does not depend on pre-generated outputs or private working folders.

## Capabilities

- multi-source directed acyclic irrigation networks;
- conveyance and application losses;
- period and seasonal source limits;
- shared source-group envelopes;
- multiple operating and shortage scenarios;
- claimant aggregation across one or more terminal records;
- period-wise robust leximin guarantees;
- bounded adaptation at explicit source and gate controls;
- deterministic tie-break objectives after the leximin vector is fixed;
- comparator methods, source-removal ablation and recourse-frontier analysis;
- benchmark-defined factorial sensitivity analysis;
- LP residual, terminal-representation and scalability audits;
- JSON, CSV, PNG and SVG result export.

## Scientific object

For each claimant, CTI-RLex enforces one guarantee in every positive-demand period and
every scenario. Deliveries from all terminal records belonging to that claimant are
summed before fairness is evaluated. Progressive filling optimizes the complete sorted
claimant-guarantee vector. After that vector is fixed, deterministic stages maximize
nominal beneficial delivery, maximize weighted contingency delivery, and minimize
normalized reconfiguration effort.

The software does not treat max-min fairness, progressive filling, robust flow or
multi-terminal aggregation as individually new concepts. Its purpose is their
representation-consistent integration for lossy multi-source irrigation systems and a
reproducible way to test the resulting allocation.

## Installation

Python 3.11 or newer is required.

Open a terminal in the cloned repository, then run:

```bash
python -m pip install -e ".[gui]"
```

The quotes matter in zsh, the default shell on macOS, which would otherwise read `.[gui]`
as a filename pattern and report that nothing matches.

The solver-only installation is:

```bash
python -m pip install -e .
```

That installation runs the library and the solver, and nothing else. The reproducibility
instructions below draw figures, measure them and run the test suite, so to follow this
file end to end install the extra that covers all of it:

```bash
python -m pip install -e ".[repro]"
```

The commands in this file use forward slashes, which PowerShell, cmd, bash and zsh all
accept. The test suite and every result producer have been run on Windows and on Linux.

## Desktop application

Start the GUI from the project root:

```bash
python main.py
```

To force an initial language for a demonstration or automated review, use
`python main.py --language en` or `python main.py --language uz`.

Use **File → Open Benchmark** (`Ctrl+O`) to select a `benchmark.json` that follows the
CTI-RLex benchmark template. The application validates both the document structure and
the mathematical mappings before solving it.

The application opens in English by default. The **ЎЗБ / ENG** selector in the top bar
switches the complete interface between Uzbek and English without restarting the
application. The selection is remembered for the next session. Menus, dialogs, help,
table headers, status messages and dynamically generated chart labels follow the selected
language; benchmark-authored names and descriptions are preserved as source data.

The GUI provides:

1. a benchmark passport and a dynamically generated network topology;
2. base claimant guarantees, deliveries, flows and scenario-period service ratios;
3. efficiency-fairness comparison against alternative solver configurations;
4. recourse-frontier and temporal-shortage diagnostics;
5. source activation, water balance and source-criticality analysis;
6. benchmark-defined robustness sensitivity;
7. representation, feasibility and computational audits;
8. sortable tables, zoomable charts and a reproducibility-package export;
9. persistent Uzbek and English interface modes.

Base solving and extended analysis run in background threads, so the interface remains
responsive. **File → Export Result Package** (`Ctrl+E`) creates a new timestamped folder
containing serialized solutions, CSV tables, PNG/SVG charts and a manifest. No files are
written automatically when a benchmark is merely opened or solved.

## Python API

```python
from leximin.dag import load_cti_benchmark, solve_cti_rlex

model = load_cti_benchmark(
    "DATA/LittleBearRiver_2025_Benchmark/benchmark.json"
)
solution = solve_cti_rlex(model)

print(solution.guarantees)
print(solution.residuals)
```

Extended effectiveness and robustness analysis is also part of the library:

```python
import json
from pathlib import Path

from leximin.dag import load_cti_benchmark, run_full_analysis

path = Path("DATA/LittleBearRiver_2025_Benchmark/benchmark.json")
raw = json.loads(path.read_text(encoding="utf-8"))
model = load_cti_benchmark(path)
analysis = run_full_analysis(model, raw)

print(analysis["effectiveness_indicators"])
print(len(analysis["sensitivity"]))
```

`run_full_analysis` is independent of the GUI and returns one serializable mapping. It
does not read or write generated-result directories.

## Benchmark template

A benchmark document must provide internally consistent records for:

- nodes and directed edges;
- sources and claimant terminals;
- periods and scenarios;
- claimant demand;
- edge capacity and efficiency;
- period and seasonal source limits;
- shared source-group limits where used;
- terminal application efficiency;
- recourse budgets, scenario weights and control assets.

Optional `sensitivity_cases` are stored inside the same JSON document. When present,
each case supplies:

- `demand_duty_af_per_acre`;
- `conveyance_loss_multiplier`;
- `source_limit_scale`;
- `recourse_budget_scale`.

The included Little Bear River benchmark is data-informed. Its claimants are irrigation
company service areas, not identified individual farmers. Its parameter status and
scientific limitations are recorded inside the benchmark metadata and must be retained
when results are interpreted.

## Reproducing the published results

Every number reported in the article is produced by a script in `scripts/` and written to
a file in `results/`. Run them from the repository root, in this order:

```bash
# 1. base solution
python -B scripts/run_cti_rlex.py DATA/LittleBearRiver_2025_Benchmark/benchmark.json --output results/cti_rlex_base.json

# 2. comparators, source ablation, 135-case factorial, scalability
python -B scripts/run_cti_experiments.py DATA/LittleBearRiver_2025_Benchmark/benchmark.json --sensitivity-cases DATA/LittleBearRiver_2025_Benchmark/data/sensitivity_cases.csv --output results/cti_rlex_experiments.json

# 3. residual, feasibility and terminal-representation audits
python -B scripts/run_cti_verification.py DATA/LittleBearRiver_2025_Benchmark/benchmark.json --output results/cti_rlex_verification.json

# 4. both instances: lexicographic vector against a common floor
python -B scripts/revision_experiments.py

# 5. guarantee vector under three recourse-budget regimes
python -B scripts/equal_budget_experiment.py

# 6. severity sweep of the canal-restriction scenario, then the scalability sweep
python -B scripts/restriction_threshold_experiment.py
python -B scripts/scalability_experiment.py

# 7. published CSV tables and PNG/SVG figures, then Figure 4 and a resolution check
python -B scripts/create_results_artifacts.py
python -B scripts/update_figure4_two_panel.py
python -B scripts/verify_publication_figures.py

# 8. machine and solver versions behind the reported solve times
python -B scripts/record_environment.py
```

Run them in this order: step 7 reads the files written by steps 1 to 3. Every script puts
`src/` on the import path itself, so a fresh clone works without installing the package
first.

The mapping from article object to file is:

| Article object | Script | Result file |
|---|---|---|
| Tables 1, 2, 5, 6 and Figures 3, 5–8 | `run_cti_experiments.py` | `results/cti_rlex_experiments.json` |
| Table 4 and Supplementary Table S16, source ablation | `ablation_experiment.py` | `results/ablation_lbr.json`, `results/ablation_cv.json` |
| Table 3, Figure 4(b), Supplementary Tables S6, S8, S9, S15 | `revision_experiments.py` | `results/revision_experiments.json` |
| Supplementary Tables S10, S11 | `equal_budget_experiment.py` | `results/equal_budget_experiment.json` |
| Supplementary Table S12 | `restriction_threshold_experiment.py` | `results/restriction_threshold.json` |
| Supplementary Tables S13, S14 | `scalability_experiment.py` | `results/scalability_cache_valley.json` |
| Supplementary Table S20, acyclicity-repair order sensitivity | `connector_order_experiment.py` | `results/connector_order_sensitivity.json`, `results/repair_inputs_cache_valley.json` |
| Supplementary Table S21, excluded service areas | `excluded_service_areas.py` | `results/excluded_service_areas.json` |
| Supplementary Table S22, effort-coefficient normalization | `normalization_sensitivity.py` | `results/normalization_sensitivity.json` |
| Supplementary Tables S24, S25, factorial effect decomposition | `factorial_decomposition.py` | `results/factorial_decomposition.json` |
| Supplementary Table S27, component-level analysis | `component_analysis.py` | `results/component_analysis.json` |
| Supplementary Tables S32 to S35, ten-claimant audit layer | `cache_valley_audit.py` | `results/cache_valley_audit.json` |
| Supplementary Tables S28 to S31, parameter provenance and coefficients | `benchmark_parameter_tables.py` | `results/benchmark_parameters.json` |
| Published CSV tables | `create_results_artifacts.py` | `results/tables/*.csv` |
| Published figures | `create_results_artifacts.py`, `update_figure4_two_panel.py` | `results/figures/*.png`, `*.svg` |
| Figure 1, benchmark network map | `DATA/LittleBearRiver_2025_Benchmark/plot_benchmark_map.py` | `DATA/LittleBearRiver_2025_Benchmark/little_bear_river_2025_benchmark_map.png`, `.svg` |
| Figure 2, solution-workflow schematic | none: drawn, not computed | `results/figures/Figure_2_cti_rlex_solution_workflow.png`, `.svg` |
| Figure resolution and font check | `verify_publication_figures.py` | printed report, no file written |
| Reported solve times | `record_environment.py` | `results/environment.json` |


Figure files are named for the order in which they were written, not for the order the
article prints them, so the mapping is stated here and every entry is resolved by
`scripts/verify_publication_figures.py`. The printed width is what the type size of a
figure has to be legible at: the two producing scripts draw on one 7.1 inch canvas and let
the journal reduce.

| Article | File, under `results/figures/` unless stated | Printed width |
|---|---|---|
| Figure 1 | `DATA/LittleBearRiver_2025_Benchmark/little_bear_river_2025_benchmark_map` | 18 cm |
| Figure 2 | `Figure_2_cti_rlex_solution_workflow` | 18 cm |
| Figure 3 | `Figure_1_claimant_guarantees` | 14 cm |
| Figure 4 | `Figure_6_method_tradeoff_two_panel` | 14 cm |
| Figure 5 | `Figure_2_recourse_frontier` | 18 cm |
| Figure 6 | `Figure_3_period_service_heatmap` | 18 cm |
| Figure 7 | `Figure_4_source_activation_water_balance` | 18 cm |
| Figure 8 | `Figure_5_sensitivity_heatmaps` | 14 cm |

`Figure_6_method_tradeoff` is the single-panel form that Figure 4 replaced. It is still
produced so that form stays reproducible; the article does not print it.

Figure 2 is the one figure in the article that is not computed: it is a drawn schematic of
the solution workflow, shipped as PNG and SVG, and the SVG is its editable source. Every
other figure is regenerated by the scripts above from a file in `results/`.

The map is drawn from the same open layers the benchmark is generated from, so
`LEXIMIN_DATASETS` has to point at them before `plot_benchmark_map.py` will run.

`results/discrimination/k1.py` and `k1b.py` are the exploratory scripts that first
established the discrimination result, and `k1_leximin_vs_common_floor.txt` and
`k1_sorted_vector_comparison.txt` are the terminal output of that first run, kept as a
record of it. The scripts themselves write no file; the published result is produced by
`scripts/revision_experiments.py`, and every guarantee, sorted vector and delivery figure
in the two transcripts is one that file carries.

The two solve times in them are not. They are single ad-hoc measurements taken before the
timing protocol below existed, so they differ from the medians the article reports and
are not comparable with them; every runtime in the article and in `results/` comes from
`scripts/timing_protocol.py`.

`scripts/rerun_all_results.py` runs the whole sequence above, together with the seven
producers listed in the table, in the order the later ones need the earlier output. It
prints the values that a correct rerun must reproduce unchanged, and skips the two steps
that need the raw open-data layers when `LEXIMIN_DATASETS` is not set:

```bash
python scripts/rerun_all_results.py
```

### Timing protocol

Every solve time published in the article and in these files is the **median of five
repeats** of a single protocol, implemented once in `scripts/timing_protocol.py` and imported
by every producing script, so the same configuration cannot be reported with two different
numbers. Alongside the median, each record carries `min_runtime_seconds`,
`max_runtime_seconds` and the raw `runtime_seconds_repeats`, so a rerun can be compared
against the measured spread rather than against a single number. Runtimes depend on the
machine and on operating-system scheduling; the processor, memory, operating system and the
exact Python, SciPy and HiGHS versions behind the published times are recorded in
`results/environment.json`. Every other number in `results/` is a property of the model and
the data rather than of the machine. On the stack recorded in `results/environment.json`
a rerun reproduces them exactly: the run that set the solver tolerances explicitly
rewrote every result file and moved nothing but the timings. On a different platform or
a different HiGHS build, expect agreement within the tolerances and the reported
precision the accompanying article declares, rather than bit-for-bit equality.

The solver configuration is set by this package rather than inherited from your install.
`src/leximin/dag/lp.py` defines `LP_FEASIBILITY_TOLERANCE` and passes it to HiGHS as both
the primal and the dual feasibility tolerance on every solve, with presolve on and no
thread count set. `results/environment.json` records the options that were actually
passed, read from that module rather than described beside it, so a rerun can be compared
against the configuration that produced the published numbers.

## Reproducibility checks

Run the automated test suite with:

```bash
python -B -m pytest
```

The tests cover schema consistency, physical balances, robust guarantees, comparator
behavior, recourse, scaling, terminal-representation invariance and GUI integration.

A benchmark rebuild is itself a regression test. Re-running a generator against unchanged
input layers must leave that benchmark's `checksums_sha256.txt` untouched:

```bash
# Point LEXIMIN_DATASETS at your own copy of the open Utah layers; the path below is only
# an example. The layers themselves are listed in the benchmark provenance files.
#   bash, zsh:   export LEXIMIN_DATASETS=/data/DataSETs
#   PowerShell:  $env:LEXIMIN_DATASETS = "C:\DataSETs"
python -B DATA/LittleBearRiver_2025_Benchmark/generate_benchmark.py
git diff --exit-code DATA/LittleBearRiver_2025_Benchmark/checksums_sha256.txt
```

The ten-claimant county instance rebuilds the same way, in the two passes its construction
needs: the shared source groups are derived from the claimant set, but which service areas
keep a route is known only after the acyclicity repair has run, so the first pass stops
there and the second rebuilds from the survivors on the same path set.

```bash
# Point LEXIMIN_DATASETS at your own copy of the open Utah layers; the path below is only
# an example. The layers themselves are listed in the benchmark provenance files.
#   bash, zsh:   export LEXIMIN_DATASETS=/data/DataSETs
#   PowerShell:  $env:LEXIMIN_DATASETS = "C:\DataSETs"
python -B scripts/rebuild_cache_valley.py
git diff --exit-code DATA/CacheValley_2025_Benchmark/benchmark.json
```

The county-wide discovery pass over the raw layers is served from the published
`selection.json`, which the rebuild only reads, so both passes take minutes rather than
hours.

## Repository layout

- `main.py` — desktop application entry point;
- `src/leximin/dag/` — benchmark loader, LP model, CTI-RLex solver, comparators,
  analysis and verification;
- `src/leximin/gui/` — standalone PyQt6 interface and dynamic chart generation;
- `tests/` — solver, benchmark and GUI checks;
- `DATA/LittleBearRiver_2025_Benchmark/` — the three-claimant benchmark, its normalized
  CSV layers, provenance, checksums and the deterministic generator that builds it from
  the open Utah layers;
- `DATA/CacheValley_2025_Benchmark/` — the ten-claimant county-wide benchmark with the
  same layer structure, its selection and discovery records and its validation report. Its
  canonical JSON, normalized CSV layers, checksums and the ordered decision record for all
  41 connector candidates are published, and so is the county-scale driver that assembles
  it from the open Utah layers, so the byte-for-byte rebuild check above covers both
  instances;
- `DATA/benchmarks_dag/` — the benchmark schema (`SCHEMA_DAG.md`) and the compact DAG
  export of the Cache Valley instance used by the desktop application;
- `scripts/` — the experiment scripts that produce the published numbers and figures;
- `results/` — the result files those scripts write, together with the published tables
  and figures.

Only the experiment scripts are published here. The tools used to typeset the manuscript
are working code and are kept out of this repository.

Benchmark generators read the open-data root from `LEXIMIN_DATASETS`, falling back to
`DataSETs/` beside the repository.

Generated exports are user-selected run artifacts and are not required by the source
repository.

## Citation

Every release of this repository is archived on Zenodo. The concept DOI below is stable
and always resolves to the most recent version:

**https://doi.org/10.5281/zenodo.22160054**

Each individual release also receives its own version DOI, which is immutable. Use the
concept DOI to refer to the software in general, and a version DOI together with the
commit hash to refer to the one archived state a set of numbers came from. The Data
Availability Statement of the accompanying article names the repository and the commit;
the version DOI of the archived release is added there at submission, once the release
that matches the submitted manuscript exists.

Machine-readable citation metadata is in `CITATION.cff`. If you use this software or
either benchmark, please cite both the software and the accompanying article.

## License

This project is distributed under the MIT License.
