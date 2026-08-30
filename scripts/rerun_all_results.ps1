# Re-run every published result producer under one timing protocol.
#
# The reviewer found that solve times disagreed between the manuscript, the Supplementary
# Material and the archived JSON files, because the three sources came from three separate
# measurement runs. Every producer now times through scripts/timing_protocol.py, so one run
# of this script leaves a single, self-consistent set of numbers behind.
#
# Run it from the repository root, on the machine whose description belongs in the article:
#
#     powershell -ExecutionPolicy Bypass -File scripts\rerun_all_results.ps1
#
# It writes only into results\. It does not commit and does not push.

$ErrorActionPreference = "Stop"

if (-not (Test-Path "scripts\timing_protocol.py")) {
    Write-Host "Run this from the repository root (C:\Projects\Leximin)." -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = "src"
$started = Get-Date

Write-Host "`n=== environment ===" -ForegroundColor Cyan
python -c "import sys, numpy, scipy; print('python', sys.version.split()[0], '| numpy', numpy.__version__, '| scipy', scipy.__version__)"
python -c "import sys; sys.path.insert(0,'scripts'); import timing_protocol as t; print('timing repeats:', t.REPEATS)"

function Step([int]$number, [string]$title, [scriptblock]$work) {
    Write-Host "`n=== $number. $title ===" -ForegroundColor Cyan
    $t0 = Get-Date
    & $work
    if ($LASTEXITCODE -ne 0) {
        Write-Host "step $number failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit 1
    }
    Write-Host ("   done in {0:N1} s" -f ((Get-Date) - $t0).TotalSeconds) -ForegroundColor DarkGray
}

Step 1 "base solution" {
    python -B scripts\run_cti_rlex.py DATA\LittleBearRiver_2025_Benchmark\benchmark.json --output results\cti_rlex_base.json
}
Step 2 "comparators, ablation, 135-case factorial, scalability (the long one)" {
    python -B scripts\run_cti_experiments.py DATA\LittleBearRiver_2025_Benchmark\benchmark.json --sensitivity-cases DATA\LittleBearRiver_2025_Benchmark\data\sensitivity_cases.csv --output results\cti_rlex_experiments.json
}
Step 3 "effect decomposition of the factorial design" { python -B scripts\factorial_decomposition.py }
Step 4 "residual, feasibility and representation audits" {
    python -B scripts\run_cti_verification.py DATA\LittleBearRiver_2025_Benchmark\benchmark.json --output results\cti_rlex_verification.json
}
Step 5 "lexicographic vector against a common floor" { python -B scripts\revision_experiments.py }
Step 6 "component-level analysis of the ten-claimant instance" { python -B scripts\component_analysis.py }
Step 7 "audit layer of the ten-claimant instance" { python -B scripts\cache_valley_audit.py }
Step 8 "parameter provenance and coefficient tables" { python -B scripts\benchmark_parameter_tables.py }
Step 9 "source-removal ablation on both instances" { python -B scripts\ablation_experiment.py }
Step 10 "guarantee vector under three recourse-budget regimes" { python -B scripts\equal_budget_experiment.py }
Step 11 "guarantee vector under three effort-coefficient weightings" { python -B scripts\normalization_sensitivity.py }
Step 12 "canal-restriction severity sweep" { python -B scripts\restriction_threshold_experiment.py }
Step 13 "scalability sweep" { python -B scripts\scalability_experiment.py }
Step 14 "acyclicity-repair order sensitivity and excluded service areas" {
    if ($env:LEXIMIN_DATASETS) {
        python -B scripts\excluded_service_areas.py
        python -B scripts\connector_order_experiment.py --build --rebuild
    } else {
        python -c "print('   skipped: these rebuild from the raw Utah layers; set LEXIMIN_DATASETS to the open-data root first')"
    }
}
Step 15 "published CSV tables and figures" { python -B scripts\create_results_artifacts.py }
Step 16 "Figure 4" { python -B scripts\update_figure4_two_panel.py }
Step 17 "figure resolution check" { python -B scripts\verify_publication_figures.py }
Step 18 "machine and solver versions" { python -B scripts\record_environment.py }
Step 19 "test suite" { python -B -m pytest -q }

$summary = @'
import json
from pathlib import Path

experiments = json.loads(Path("results/cti_rlex_experiments.json").read_text(encoding="utf-8"))
verification = json.loads(Path("results/cti_rlex_verification.json").read_text(encoding="utf-8"))
revision = json.loads(Path("results/revision_experiments.json").read_text(encoding="utf-8"))
scalability = json.loads(Path("results/scalability_cache_valley.json").read_text(encoding="utf-8"))
environment = json.loads(Path("results/environment.json").read_text(encoding="utf-8"))

methods = {row["method"]: row for row in experiments["method_comparison"]}
util, rlex = methods["UTIL-BR"], methods["CTI-RLex proposed"]
rigid, nominal = methods["CTI-RLex rigid"], methods["CTI-RLex nominal only"]
cache = revision["cache_valley_v3"]
factorial = [case["minimum_guarantee"] for case in experiments["sensitivity"]]
sorted_base = sorted(verification["base_guarantees"].values())

print("  these must NOT have changed")
print("    three-claimant vector       " + " ".join(f"{v:.4f}" for v in sorted_base) + "    expected 0.4195 0.4195 0.4477")
print(f"    UTIL-BR minimum guarantee   {util['minimum_guarantee']:.4f}                 expected 0.1077")
print(f"    CTI-RLex minimum guarantee  {rlex['minimum_guarantee']:.4f}                 expected 0.4195")
print(f"    sigma_2 CTI-RLex / PROP-BR  {cache['cti_rlex']['sorted_rho'][1]:.4f} / {cache['prop_br']['sorted_rho'][1]:.4f}        expected 0.1374 / 0.0564")
print(f"    price of fairness           {100*(util['nominal_beneficial_delivery_af']-rlex['nominal_beneficial_delivery_af'])/util['nominal_beneficial_delivery_af']:.2f}%                  expected 2.57%")
print(f"    value of recourse           {100*(rlex['minimum_guarantee']-rigid['minimum_guarantee'])/rigid['minimum_guarantee']:.2f}%                  expected 9.22%")
print(f"    robustness cost             {100*(nominal['nominal_beneficial_delivery_af']-rlex['nominal_beneficial_delivery_af'])/nominal['nominal_beneficial_delivery_af']:.1f}%                  expected 31.5%")
print(f"    factorial range             {min(factorial):.4f} to {max(factorial):.4f}     expected 0.2243 to 0.7011")

print("")
print("  these ARE expected to change - the timings being fixed")
def spread(row):
    low, high, repeats = row.get("min_runtime_seconds"), row.get("max_runtime_seconds"), row.get("repeats")
    if low is None or high is None:
        return "   (no spread recorded - old protocol)"
    return f"   range {low:.3f}-{high:.3f} over {repeats} repeats"

for row in experiments["scalability"]:
    con = row["equality_constraints"] + row["inequality_constraints"]
    print(f"    Table 6, {row['scenario_count']} scenario(s)      {row['variables']:4d} var; {con:4d} con; "
          f"{row['median_runtime_seconds']:.3f} s" + spread(row))
for row in scalability:
    if (row["claimants"], row["scenarios"]) in {(2, 5), (10, 1), (10, 5), (3, 5)}:
        print(f"    S14 {row['benchmark']:16s} K={row['claimants']:2d} S={row['scenarios']}   "
              f"{row['runtime_s']:.3f} s" + spread(row))
print(f"    revision, Cache Valley solve   {cache['cti_rlex']['runtime_s']:.3f} s")
print("")
print(f"  machine: {environment['processor']}, {environment['logical_cores']} cores, {environment['operating_system']}")
print(f"           Python {environment['python']}, NumPy {environment['numpy']}, SciPy {environment['scipy']}")
'@

Write-Host "`n=== key numbers ===" -ForegroundColor Cyan
$summary | python -

Write-Host "`n=== files git sees as changed ===" -ForegroundColor Cyan
git status --short

Write-Host ("`nfinished in {0:N1} s. Nothing was committed and nothing was pushed." -f ((Get-Date) - $started).TotalSeconds) -ForegroundColor Green
Write-Host "Send me the output above; then I regenerate the manuscript and the supplement." -ForegroundColor Green
