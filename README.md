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

```powershell
python -m pip install -e .[gui]
```

The solver-only installation is:

```powershell
python -m pip install -e .
```

## Desktop application

Start the GUI from the project root:

```powershell
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

```powershell
# 1. base solution
python -B scripts\run_cti_rlex.py DATA\LittleBearRiver_2025_Benchmark\benchmark.json `
    --output results\cti_rlex_base.json

# 2. comparators, source ablation, 135-case factorial, scalability
python -B scripts\run_cti_experiments.py DATA\LittleBearRiver_2025_Benchmark\benchmark.json `
    --sensitivity-cases DATA\LittleBearRiver_2025_Benchmark\data\sensitivity_cases.csv `
    --output results\cti_rlex_experiments.json

# 3. residual, feasibility and terminal-representation audits
python -B scripts\run_cti_verification.py DATA\LittleBearRiver_2025_Benchmark\benchmark.json `
    --output results\cti_rlex_verification.json

# 4. both instances: lexicographic vector against a common floor
python -B scripts\revision_experiments.py

# 5. guarantee vector under three recourse-budget regimes
python -B scripts\equal_budget_experiment.py

# 6. severity sweep of the canal-restriction scenario, then the scalability sweep
python -B scripts\restriction_threshold_experiment.py
python -B scripts\scalability_experiment.py

# 7. published CSV tables and PNG/SVG figures, then Figure 4 and a resolution check
python -B scripts\create_results_artifacts.py
python -B scripts\update_figure4_two_panel.py
python -B scripts\verify_publication_figures.py

# 8. machine and solver versions behind the reported solve times
python -B scripts\record_environment.py
```

Run them in this order: step 7 reads the files written by steps 1 to 3. Every script puts
`src/` on the import path itself, so a fresh clone works without installing the package
first.

The mapping from article object to file is:

| Article object | Script | Result file |
|---|---|---|
| Tables 1, 2, 5, 6 and Figures 3, 5–8 | `run_cti_experiments.py` | `results/cti_rlex_experiments.json` |
| Table 4 and Supplementary S16, source ablation | `run_cti_experiments.py` | `results/ablation_lbr.json`, `results/ablation_cv.json` |
| Table 3, Figure 4(b), Supplementary S6, S8, S9, S15 | `revision_experiments.py` | `results/revision_experiments.json`, `results/cache_valley_per_claimant.json` |
| Supplementary S10, S11 | `equal_budget_experiment.py` | `results/equal_budget_experiment.json` |
| Supplementary S12 | `restriction_threshold_experiment.py` | `results/restriction_threshold.json` |
| Supplementary S13, S14 | `scalability_experiment.py` | `results/scalability_cache_valley.json` |
| Published CSV tables | `create_results_artifacts.py` | `results/tables/*.csv` |
| Published figures | `create_results_artifacts.py`, `update_figure4_two_panel.py` | `results/figures/*.png`, `*.svg` |
| Figure resolution and font check | `verify_publication_figures.py` | printed report, no file written |
| Reported solve times | `record_environment.py` | `results/environment.json` |

`results/discrimination/k1.py` and `k1b.py` are the exploratory scripts that first
established the discrimination result. They print to the terminal and write nothing; the
published file is produced by `scripts/revision_experiments.py`.

## Reproducibility checks

Run the automated test suite with:

```powershell
python -B -m pytest
```

The tests cover schema consistency, physical balances, robust guarantees, comparator
behavior, recourse, scaling, terminal-representation invariance and GUI integration.

A benchmark rebuild is itself a regression test. Re-running a generator against unchanged
input layers must leave that benchmark's `checksums_sha256.txt` untouched:

```powershell
# Point LEXIMIN_DATASETS at your own copy of the open Utah layers; the path below is only
# an example. The layers themselves are listed in the benchmark provenance files.
$env:LEXIMIN_DATASETS = "C:\DataSETs"
python -B DATA\LittleBearRiver_2025_Benchmark\generate_benchmark.py
git diff --exit-code DATA/LittleBearRiver_2025_Benchmark/checksums_sha256.txt
```

This check covers the Little Bear River instance, whose generator is published here.

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
  same layer structure, its selection and discovery records and its validation report.
  Its canonical JSON, normalized CSV layers, checksums and connector accept/reject log are
  published; the county-scale discovery script that assembled it from the open Utah layers
  is not part of this release, so the byte-for-byte rebuild check below applies to the
  Little Bear River instance only;
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

Each individual release also receives its own version DOI, which is immutable. The
accompanying article cites a version DOI together with the exact commit hash, so that the
numbers reported there can be traced to one archived state. Use the concept DOI to refer
to the software in general, and a version DOI to refer to a specific archived state.

Machine-readable citation metadata is in `CITATION.cff`. If you use this software or
either benchmark, please cite both the software and the accompanying article.

## License

This project is distributed under the MIT License.
