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
a file in `results/`. From the repository root:

```powershell
python -B scripts\run_cti_rlex.py             # base solution
python -B scripts\run_cti_experiments.py      # comparators, ablation, 135-case factorial
python -B scripts\run_cti_verification.py     # residual and representation audits
python -B scripts\equal_budget_experiment.py  # guarantee vector under three budget regimes
python -B scripts\restriction_threshold_experiment.py  # severity sweep of the canal restriction
python -B scripts\record_environment.py       # machine and solver versions for the timings
```

The mapping from article object to file is:

| Article object | Script | Result file |
|---|---|---|
| Tables 1, 2, 5, 6 and Figures 3, 5–8 | `run_cti_experiments.py` | `results/cti_rlex_experiments.json` |
| Table 4, source ablation | `run_cti_experiments.py` | `results/ablation_lbr.json`, `results/ablation_cv.json` |
| Table 3, Figure 4(b), Supplementary S6, S8, S9 | `results/discrimination/k1.py` | `results/revision_experiments.json` |
| Supplementary S10, S11 | `equal_budget_experiment.py` | `results/equal_budget_experiment.json` |
| Supplementary S12 | `restriction_threshold_experiment.py` | `results/restriction_threshold.json` |
| Supplementary S13, S14 | `run_cti_experiments.py` | `results/scalability_cache_valley.json` |
| Reported solve times | `record_environment.py` | `results/environment.json` |

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
$env:LEXIMIN_DATASETS = "C:\DataSETs"
python -B DATA\LittleBearRiver_2025_Benchmark\generate_benchmark.py
git diff --exit-code DATA/LittleBearRiver_2025_Benchmark/checksums_sha256.txt
```

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
  same layer structure, its selection and discovery records and its validation report;
- `scripts/` — the experiment scripts that produce the published numbers and figures;
- `results/` — the result files those scripts write, together with the published tables
  and figures.

Only the experiment scripts are published here. The tools used to typeset the manuscript
are working code and are kept out of this repository.

Benchmark generators read the open-data root from `LEXIMIN_DATASETS`, falling back to
`DataSETs/` beside the repository.

Generated exports are user-selected run artifacts and are not required by the source
repository.

## License

This project is distributed under the MIT License.
