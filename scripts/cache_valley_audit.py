"""The audit layer of the three-claimant instance, applied to the ten-claimant one.

The larger instance carries the paper's discriminating claim -- that a complete
lexicographic vector separates from a common floor -- and it is the instance whose audit is
thinnest. The smaller one is published with a full scenario-period service matrix, a water
balance, a source-activation schedule and a residual report; the larger one is published
with a claimant register and a level trace. A reader who wants to check the discriminating
result cell by cell cannot.

This produces the same four layers for the ten-claimant instance, from the same routines the
smaller one uses, so the two audits are comparable rather than merely similar.

Three properties are asserted rather than reported, because each is a way the layer could be
silently wrong:

    the guarantee is the minimum of its own cells, for every claimant, which is what makes
    the binding flags mean anything;
    no cell falls below the guarantee it is measured against, which is the constraint the
    program is supposed to enforce;
    the water balance closes: injection less conveyance and application losses equals
    beneficial delivery, in every scenario.

Run:  python scripts/cache_valley_audit.py
Writes: results/cache_valley_audit.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from timing_protocol import timed  # noqa: E402

from leximin.dag import (  # noqa: E402
    load_cti_benchmark,
    representation_invariance_error,
    solve_cti_rlex,
)
from leximin.dag.analysis import operational_audit  # noqa: E402

BENCHMARK = REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json"
OUTPUT = REPO / "results" / "cache_valley_audit.json"

BINDING_TOLERANCE = 1e-7   # the blocking tolerance of Section 2.7
BALANCE_TOLERANCE = 0.05   # acre-feet, the precision the tables print
SPLITS = (2, 4, 8)


def service_matrix(model, solution) -> list[dict[str, Any]]:
    """Every claimant-period-scenario cell, with the demand and delivery behind its ratio."""

    terminals: dict[str, list[str]] = {}
    for terminal in model.terminals:
        terminals.setdefault(terminal.claimant_id, []).append(terminal.terminal_id)

    rows = []
    for scenario in model.scenarios:
        for period in model.periods:
            for claimant in model.claimants:
                delivered = sum(
                    solution.beneficial_delivery[scenario, period, terminal]
                    for terminal in terminals[claimant]
                )
                demand = model.demand[period, claimant]
                ratio = solution.period_service_ratio[scenario, period, claimant]
                guarantee = solution.guarantees[claimant]
                rows.append({
                    "scenario_id": scenario,
                    "period_id": period,
                    "claimant_id": claimant,
                    "demand_af": demand,
                    "beneficial_delivery_af": delivered,
                    "service_ratio": ratio,
                    "guarantee": guarantee,
                    "binding": abs(ratio - guarantee) <= BINDING_TOLERANCE,
                })
    return rows


def main() -> None:
    raw = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    model = load_cti_benchmark(BENCHMARK)
    solution, timing = timed(lambda: solve_cti_rlex(model))

    audit = operational_audit(model, solution, raw)
    matrix = service_matrix(model, solution)

    # ---- the three assertions. Each is a way the layer could be silently wrong.
    for claimant in model.claimants:
        cells = [row["service_ratio"] for row in matrix if row["claimant_id"] == claimant]
        guarantee = solution.guarantees[claimant]
        if abs(min(cells) - guarantee) > BINDING_TOLERANCE:
            raise SystemExit(
                f"{claimant}: the smallest cell is {min(cells):.9f} but the guarantee is "
                f"{guarantee:.9f}; the matrix and the solution disagree"
            )
        if min(cells) < guarantee - BINDING_TOLERANCE:
            raise SystemExit(f"{claimant}: a cell falls below its own guarantee")

    for row in audit["scenario_water_balance"]:
        closed = (
            row["source_injection_af"]
            - row["conveyance_loss_af"]
            - row["application_loss_af"]
        )
        if abs(closed - row["beneficial_delivery_af"]) > BALANCE_TOLERANCE:
            raise SystemExit(
                f"{row['scenario_id']}: the water balance does not close, "
                f"{closed:.2f} against {row['beneficial_delivery_af']:.2f} acre-ft"
            )

    # ---- the representation test the smaller instance also reports.
    splits = []
    terminal = sorted(model.terminals, key=lambda item: item.terminal_id)[0]
    for count in SPLITS:
        error, _original, _split = representation_invariance_error(
            model, terminal.terminal_id, count
        )
        splits.append({
            "terminal_id": terminal.terminal_id,
            "claimant_id": terminal.claimant_id,
            "records": count,
            "max_guarantee_change": error,
        })

    binding = [row for row in matrix if row["binding"]]
    payload = {
        "benchmark_id": model.benchmark_id,
        "claimants": len(model.claimants),
        "cells": len(matrix),
        "binding_cells": len(binding),
        "binding_tolerance": BINDING_TOLERANCE,
        "guarantees": dict(solution.guarantees),
        "residuals": dict(solution.residuals),
        "representation_tests": splits,
        "scenario_water_balance": audit["scenario_water_balance"],
        "source_activation": audit["source_activation"],
        "most_utilized_edges": audit["most_utilized_edges"],
        "most_utilized_source_groups": audit["most_utilized_source_groups"],
        "service_matrix": matrix,
        **timing,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"{payload['cells']} claimant-period-scenario cells, "
          f"{payload['binding_cells']} binding")
    print("  residuals: " + ", ".join(
        f"{key.replace('max_', '').replace('_', ' ')} {value:.3e}"
        for key, value in sorted(solution.residuals.items())
    ))
    print(f"  representation tests on {terminal.terminal_id}: "
          + ", ".join(f"{row['records']} records {row['max_guarantee_change']:.2e}"
                      for row in splits))
    print("  water balance by scenario:")
    for row in audit["scenario_water_balance"]:
        print(f"    {row['scenario_id']:<44} injection {row['source_injection_af']:>9.1f}  "
              f"beneficial {row['beneficial_delivery_af']:>9.1f}  "
              f"efficiency {row['end_to_end_efficiency']:.4f}")
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
