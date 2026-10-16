"""What does the objective hierarchy determine, and what does it leave open? (Reviewer 3, point 2)

The solver fixes the guarantee vector by progressive filling and then maximizes nominal
delivery, maximizes weighted contingency delivery and minimizes recourse effort, each stage
preserving the optima before it within the preservation tolerance. The manuscript said that
these stages "break the remaining ties", and the Supplementary Material that the reported
schedule does "not depend on solver degeneracy". A reviewer rightly answered that three
objectives can still leave many optimal plans, and asked that three things be kept apart:
the specified hierarchy, reproducibility within the pinned environment, and uniqueness of
the flow realization. This script measures each of them separately. It claims no unique
schedule; it reports which quantities the hierarchy fixes and how far the others can move.

1. What the hierarchy determines. The optimal face of a rule is the feasible set with that
   rule's guarantees fixed, both delivery optima preserved and the recourse effort held at its
   optimum, each within the solver's own preservation tolerance. Over the face of CTI-RLex
   every reported quantity is minimized and maximized:

     * the delivered-demand ratio of each claimant in each scenario and period (Figure 6);
     * the seasonal service ratio of each claimant in each scenario (Table 1);
     * the seasonal injection of each source in each scenario (Figure 7a);
     * the beneficial delivery, the source injection, the conveyance loss and the application
       loss of each scenario (Table 2 and Figure 7), and from them the end-to-end efficiency;
     * the normalized recourse effort of each contingency scenario (Figure 5b);

   and, as a diagnostic the paper does not report as a result, the flow on every reach in
   every scenario and period of the three-claimant instance and the seasonal flow through
   every head gate of the county instance.

   A quantity is determined when its range on the face is at most 1e-6, ten times the
   preservation tolerance: in absolute terms for a service ratio, relative to its value (at
   least 1) for recourse effort, and relative to the larger of its value and the instance's
   nominal delivery for a volume, so that a volume near zero is not held to a millionth of
   an acre-foot. A wider range can come from two sources: genuine freedom in the plan, or
   the tolerance itself, because a preserved optimum may fall short by 1e-7 of its value and
   a later stage can spend that slack. The two are told apart on the anchored face, the
   subset of the face on which nominal delivery, weighted contingency delivery and recourse
   effort sit at their lexicographic optimum within the face (three more linear programs,
   each preserving the one before it to within 1e-10, a thousandth of the published
   tolerance; with no tolerance at all a few of the county programs end in an unknown
   status). A quantity whose range collapses there is determined up to the preservation
   tolerance; one whose range does not is undetermined.

   The guarantee vector itself is unique, which the manuscript proves; as a numerical check,
   the guarantee each claimant realizes, the smallest ratio over its cells, is minimized and
   maximized over the face and must equal the claimant's guarantee in every optimal plan.

   A cell is binding when its ratio is within 1e-7 of the claimant's guarantee, the test of
   Figure 6 and Table 1. On the face a cell is binding in every optimal plan, in some, or in
   none, and the three are reported per claimant. Every optimal plan binds every claimant
   somewhere, because the guarantee of a frozen claimant cannot be raised; which cell binds
   is what can change.

2. The comparators. PROP-BR and UTIL-BR fix one common floor for every claimant and then run
   the same three stages, so the guarantee each claimant realizes above that floor is a
   property of the plan rather than of the rule. For each claimant the range of its realized
   guarantee over the rule's face is reported, a range wider than 1e-6 being checked on the
   rule's anchored face as above; then the range of each scenario's delivery, and whether
   the CTI-RLex plan is itself one of the rule's optimal plans. For PROP-BR, the comparator
   Table 3 and Figure 4b set against the lexicographic vector, the most favorable sorted
   vector its face admits is computed as well, by progressive filling restricted to the
   face, so that the comparison does not rest on the plan the solver happened to return.

The faces are degenerate by construction, and a few of their programs end in an unknown
status at the published settings (on SciPy 1.17.0 one county program does so with presolve
on and off alike). Every program is therefore solved at the published settings first and,
only if that returns no optimum, with presolve off, then by the interior-point method, then
by the dual simplex method under Dantzig pricing without presolve. How often each was needed
is reported. A quantity that no method resolves is reported as unresolved, not estimated.

3. Reproducibility in the pinned environment. The solve is repeated and the two plans are
   compared value by value; then it is repeated with HiGHS presolve switched off, a
   different path to an optimal vertex, and the change is reported separately for the
   determined and the undetermined quantities. The first comparison is what the pinned
   environment guarantees; the second shows that a different path moves only what the
   hierarchy leaves open.

Run:  python scripts/flow_uniqueness.py
Writes: results/flow_uniqueness.json
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path

import numpy as np
from scipy.optimize import OptimizeWarning, linprog
from scipy.sparse import csr_matrix, hstack, vstack

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag import (  # noqa: E402
    OptimizationError,
    load_cti_benchmark,
    solve_cti_rlex,
    solve_robust_proportional,
    solve_utilitarian_fair,
)
from leximin.dag import lp as lp_module  # noqa: E402
from leximin.dag import solver as solver_module  # noqa: E402
from leximin.dag.experiments import (  # noqa: E402
    contingency_delivery_objective,
    nominal_delivery_objective,
    recourse_objective,
)
from leximin.dag.lp import HIGHS_OPTIONS, build_lp, objective_value  # noqa: E402

OUTPUT = REPO / "results" / "flow_uniqueness.json"
INSTANCES = {
    "little_bear_v2": REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    "cache_valley_v4": REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
}
PRESERVATION = 1e-7          # the solver's default, Section 2.7
ANCHOR = 1e-10               # the anchored face keeps each objective this close to its optimum
DETERMINED = 1e-6            # relative width at or below which a quantity is determined
BINDING = 1e-7               # the binding test of Figure 6 and Table 1
FACE_BLOCKING = (1e-7, 1e-6, 1e-5)  # blocking tolerances tried, in turn, on a comparator's face
REPORTED = (
    "period_service_ratio",
    "seasonal_service_ratio",
    "source_seasonal_injection_af",
    "scenario_beneficial_delivery_af",
    "scenario_source_injection_af",
    "scenario_conveyance_loss_af",
    "scenario_application_loss_af",
    "scenario_recourse_effort",
)
EXAMPLES = 10
UNIT = {
    "period_service_ratio": "ratio",
    "seasonal_service_ratio": "ratio",
    "source_seasonal_injection_af": "volume",
    "scenario_beneficial_delivery_af": "volume",
    "scenario_source_injection_af": "volume",
    "scenario_conveyance_loss_af": "volume",
    "scenario_application_loss_af": "volume",
    "scenario_recourse_effort": "effort",
    "reach_flow_af": "volume",
    "head_gate_seasonal_flow_af": "volume",
}

Coefficients = Mapping[tuple, float]
Quantity = tuple[str, Coefficients, Callable[[object], float]]


# --------------------------------------------------------------------------------------
# Faces


def preserved_rows(model, solution, tolerance: float = PRESERVATION) -> tuple:
    """The rows that keep a solution's three stage optima, with the solver's own rule."""

    def floor(value: float) -> float:
        return value - tolerance * max(1.0, abs(value))

    nominal = nominal_delivery_objective(model)
    contingency = contingency_delivery_objective(model)
    effort = solution.normalized_recourse_effort
    return (
        ({key: -c for key, c in nominal.items()}, -floor(solution.nominal_beneficial_delivery)),
        ({key: -c for key, c in contingency.items()}, -floor(solution.weighted_contingency_beneficial_delivery)),
        (recourse_objective(model), effort + tolerance * max(1.0, abs(effort))),
    )


def anchored_rows(model, fixed: Mapping[str, float], rows: tuple) -> tuple[tuple, dict]:
    """Rows of the anchored face: the three objectives at their optimum within the face."""

    def slack(value: float) -> float:
        return ANCHOR * max(1.0, abs(value))

    fallbacks: dict[str, int] = {}

    def optimum(problem) -> float:
        result = robust_linprog(fallbacks, c=problem.c, A_ub=problem.a_ub, b_ub=problem.b_ub,
                                A_eq=problem.a_eq, b_eq=problem.b_eq, bounds=problem.bounds)
        return objective_value(problem, result)

    nominal = nominal_delivery_objective(model)
    contingency = contingency_delivery_objective(model)
    effort = recourse_objective(model)
    nominal_anchor = optimum(build_lp(model, nominal, maximize=True, fixed_rho=dict(fixed), extra_ub=rows))
    keep_nominal = ({key: -c for key, c in nominal.items()}, -(nominal_anchor - slack(nominal_anchor)))
    contingency_anchor = optimum(build_lp(model, contingency, maximize=True, fixed_rho=dict(fixed),
                                          extra_ub=rows + (keep_nominal,)))
    keep_contingency = ({key: -c for key, c in contingency.items()},
                        -(contingency_anchor - slack(contingency_anchor)))
    effort_anchor = optimum(build_lp(model, effort, maximize=False, fixed_rho=dict(fixed),
                                     extra_ub=rows + (keep_nominal, keep_contingency)))
    anchors = {
        "nominal_delivery_af": nominal_anchor,
        "weighted_contingency_delivery_af": contingency_anchor,
        "recourse_effort": effort_anchor,
        "tolerance": ANCHOR,
        "fallbacks": fallbacks,
    }
    return rows + (keep_nominal, keep_contingency, (effort, effort_anchor + slack(effort_anchor))), anchors


FALLBACKS = (
    ("presolve off", "highs", {"presolve": False}),
    ("interior point", "highs-ipm", {}),
    ("dual simplex, Dantzig pricing, presolve off", "highs-ds",
     {"presolve": False, "simplex_dual_edge_weight_strategy": "dantzig"}),
)


def robust_linprog(fallbacks: dict[str, int], **arguments):
    """linprog at the published settings, then down FALLBACKS until one returns an optimum."""

    result = linprog(method="highs", options=dict(HIGHS_OPTIONS), **arguments)
    if result.success:
        return result
    messages = [f"published settings: {result.message}"]
    for label, method, changes in FALLBACKS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            result = linprog(method=method, options={**HIGHS_OPTIONS, **changes}, **arguments)
        if result.success:
            fallbacks[label] = fallbacks.get(label, 0) + 1
            return result
        messages.append(f"{label}: {result.message}")
    fallbacks["unresolved"] = fallbacks.get("unresolved", 0) + 1
    raise OptimizationError("face LP failed: " + "; ".join(messages))


class Face:
    """One rule's optimal face as a linear program, with min and max of linear quantities."""

    def __init__(self, model, fixed: Mapping[str, float], rows: tuple) -> None:
        self.problem = build_lp(model, {}, maximize=False, fixed_rho=dict(fixed), extra_ub=rows)
        self.fallbacks: dict[str, int] = {}

    def _solve(self, **arguments):
        return robust_linprog(self.fallbacks, **arguments)

    def vector(self, coefficients: Coefficients) -> np.ndarray:
        c = np.zeros(len(self.problem.keys))
        for key, coefficient in coefficients.items():
            c[self.problem.index[key]] += coefficient
        return c

    def minimum(self, c: np.ndarray) -> float:
        p = self.problem
        result = self._solve(c=c, A_ub=p.a_ub, b_ub=p.b_ub, A_eq=p.a_eq, b_eq=p.b_eq, bounds=p.bounds)
        return float(c @ result.x)

    def extremes(self, coefficients: Coefficients) -> tuple[float, float]:
        c = self.vector(coefficients)
        return self.minimum(c), -self.minimum(-c)

    def largest_floor(self, cells: list[Coefficients]) -> float:
        """max t subject to t <= every listed linear quantity, over the face."""

        p = self.problem
        columns = len(p.keys)
        data, rows, cols = [], [], []
        for r, coefficients in enumerate(cells):
            rows.append(r)
            cols.append(columns)
            data.append(1.0)
            for key, value in coefficients.items():
                rows.append(r)
                cols.append(p.index[key])
                data.append(-value)
        extra = csr_matrix((data, (rows, cols)), shape=(len(cells), columns + 1))
        a_ub = vstack([hstack([p.a_ub, csr_matrix((p.a_ub.shape[0], 1))]), extra]).tocsr()
        b_ub = np.concatenate([p.b_ub, np.zeros(len(cells))])
        a_eq = hstack([p.a_eq, csr_matrix((p.a_eq.shape[0], 1))]).tocsr()
        c = np.zeros(columns + 1)
        c[-1] = -1.0
        result = self._solve(c=c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=p.b_eq, bounds=list(p.bounds) + [(0.0, 1.0)])
        return float(result.x[-1])


def leximin_best(model, rows: tuple) -> tuple[dict[str, float] | None, dict]:
    """Progressive filling restricted to the plans that satisfy ``rows``: the most favorable
    sorted guarantee vector those plans admit.

    The rows make every program of the sequence degenerate, so each program is solved with
    the same fallbacks as the face programs. On such a face the level program can also stop
    short of its optimum by more than the solver's blocking tolerance of 1e-7 -- on SciPy
    1.17.0 the PROP-BR face of the county instance stops 2e-6 short -- and progressive filling
    then finds no claimant blocked. The sequence is then repeated with the blocking tolerances
    of FACE_BLOCKING, the loosest of which is still three orders of magnitude below the closest
    distinct levels of either instance, and the tolerance that completed it is reported: the
    vector is accurate to that tolerance. Returns the vector, or None if no tolerance
    completes the sequence, and a record of the fallbacks, the errors and the tolerance used.
    """

    original_build, original_run = solver_module.build_lp, solver_module.run_lp
    fallbacks: dict[str, int] = {}
    errors: dict[str, str] = {}

    def with_rows(*args, extra_ub=(), **kwargs):
        return original_build(*args, extra_ub=tuple(extra_ub) + tuple(rows), **kwargs)

    def robust_run(problem):
        return robust_linprog(fallbacks, c=problem.c, A_ub=problem.a_ub, b_ub=problem.b_ub,
                              A_eq=problem.a_eq, b_eq=problem.b_eq, bounds=problem.bounds)

    solver_module.build_lp, solver_module.run_lp = with_rows, robust_run
    try:
        for tolerance in FACE_BLOCKING:
            try:
                vector = dict(solve_cti_rlex(model, blocking_tolerance=tolerance).guarantees)
            except OptimizationError as error:
                errors[f"{tolerance:g}"] = str(error)
                continue
            return vector, {"fallbacks": fallbacks, "errors": errors, "blocking_tolerance": tolerance}
        return None, {"fallbacks": fallbacks, "errors": errors, "blocking_tolerance": None}
    finally:
        solver_module.build_lp, solver_module.run_lp = original_build, original_run


# --------------------------------------------------------------------------------------
# Quantities


def cell_coefficients(model, scenario: str, period: str, claimant: str) -> Coefficients:
    demand = model.demand[period, claimant]
    return {("x", scenario, period, t.terminal_id): 1.0 / demand for t in model.terminals_by_claimant[claimant]}


def positive_cells(model, claimant: str) -> list[tuple[str, str]]:
    return [(scenario, period) for scenario in model.scenarios for period in model.periods
            if model.demand[period, claimant] > 0]


def cti_quantities(model, instance: str) -> dict[str, list[Quantity]]:
    """Every reported quantity as (label, coefficients, value in a solution)."""

    terminals = model.terminals_by_claimant
    families: dict[str, list[Quantity]] = {name: [] for name in REPORTED}
    for scenario in model.scenarios:
        for claimant in model.claimants:
            for period in model.periods:
                if model.demand[period, claimant] <= 0:
                    continue
                families["period_service_ratio"].append((
                    f"{scenario}|{period}|{claimant}",
                    cell_coefficients(model, scenario, period, claimant),
                    lambda s, k=(scenario, period, claimant): s.period_service_ratio[k],
                ))
            seasonal_demand = sum(model.demand[period, claimant] for period in model.periods)
            families["seasonal_service_ratio"].append((
                f"{scenario}|{claimant}",
                {("x", scenario, period, t.terminal_id): 1.0 / seasonal_demand
                 for period in model.periods for t in terminals[claimant]},
                lambda s, k=(scenario, claimant): s.seasonal_service_ratio[k],
            ))
        for source in model.source_ids:
            families["source_seasonal_injection_af"].append((
                f"{scenario}|{source}",
                {("g", scenario, period, source): 1.0 for period in model.periods},
                lambda s, sc=scenario, src=source: sum(s.source_injection[sc, p, src] for p in model.periods),
            ))
        delivery = {("x", scenario, p, t.terminal_id): 1.0 for p in model.periods for t in model.terminals}
        withdrawal = {("w", scenario, p, t.terminal_id): 1.0 for p in model.periods for t in model.terminals}
        injection = {("g", scenario, p, src): 1.0 for p in model.periods for src in model.source_ids}
        families["scenario_beneficial_delivery_af"].append((
            scenario, delivery,
            lambda s, sc=scenario: sum(v for k, v in s.beneficial_delivery.items() if k[0] == sc),
        ))
        families["scenario_source_injection_af"].append((
            scenario, injection,
            lambda s, sc=scenario: sum(v for k, v in s.source_injection.items() if k[0] == sc),
        ))
        families["scenario_conveyance_loss_af"].append((
            scenario, {**injection, **{key: -1.0 for key in withdrawal}},
            lambda s, sc=scenario: sum(v for k, v in s.source_injection.items() if k[0] == sc)
            - sum(v for k, v in s.gross_terminal_withdrawal.items() if k[0] == sc),
        ))
        families["scenario_application_loss_af"].append((
            scenario, {**withdrawal, **{key: -1.0 for key in delivery}},
            lambda s, sc=scenario: sum(v for k, v in s.gross_terminal_withdrawal.items() if k[0] == sc)
            - sum(v for k, v in s.beneficial_delivery.items() if k[0] == sc),
        ))
    for scenario in model.contingency_scenarios:
        families["scenario_recourse_effort"].append((
            scenario,
            {("u", scenario, period, asset.asset_id): asset.effort_coefficient
             for period in model.periods for asset in model.controls},
            lambda s, sc=scenario: s.recourse_by_scenario[sc],
        ))
    # Diagnostics the paper does not report as results.
    if instance == "little_bear_v2":
        families["reach_flow_af"] = [
            (f"{scenario}|{period}|{edge}", {("q", scenario, period, edge): 1.0},
             lambda s, k=(scenario, period, edge): s.edge_flow[k])
            for scenario in model.scenarios for period in model.periods for edge in model.edge_ids
        ]
    else:
        gates = [asset.resource_id for asset in model.controls if asset.resource_type == "edge"]
        families["head_gate_seasonal_flow_af"] = [
            (f"{scenario}|{edge}", {("q", scenario, period, edge): 1.0 for period in model.periods},
             lambda s, sc=scenario, e=edge: sum(s.edge_flow[sc, p, e] for p in model.periods))
            for scenario in model.scenarios for edge in gates
        ]
    return families


def scaled(width: float, value: float, unit: str, volume_scale: float) -> float:
    """A width on the scale the determinacy threshold is applied to (see the module notes)."""

    if unit == "ratio":
        return width
    if unit == "volume":
        return width / max(abs(value), volume_scale)
    return width / max(1.0, abs(value))


def measure(face: Face, anchored: Face, solution, items: list[Quantity], unit: str) -> list[dict]:
    volume_scale = solution.nominal_beneficial_delivery
    rows = []
    for label, coefficients, value_of in items:
        published = value_of(solution)
        row = {"quantity": label, "published": published}
        rows.append(row)
        try:
            low, high = face.extremes(coefficients)
        except OptimizationError as error:
            row.update({"status": "unresolved", "error": str(error)})
            continue
        row.update({"minimum": low, "maximum": high, "width": high - low,
                    "scaled_width": scaled(high - low, published, unit, volume_scale)})
        if row["scaled_width"] <= DETERMINED:
            row["status"] = "determined"
            continue
        try:
            a_low, a_high = anchored.extremes(coefficients)
        except OptimizationError as error:
            row.update({"status": "unresolved", "error": f"anchored face: {error}"})
            continue
        row.update({"anchored_minimum": a_low, "anchored_maximum": a_high, "anchored_width": a_high - a_low})
        row["status"] = ("determined_up_to_preservation_tolerance"
                         if scaled(a_high - a_low, published, unit, volume_scale) <= DETERMINED
                         else "undetermined")
    return rows


def summarize(rows: list[dict], *, keep_all: bool) -> dict:
    undetermined = [row for row in rows if row["status"] == "undetermined"]
    summary = {
        "quantities": len(rows),
        "determined": sum(row["status"] == "determined" for row in rows),
        "determined_up_to_preservation_tolerance":
            sum(row["status"] == "determined_up_to_preservation_tolerance" for row in rows),
        "undetermined": len(undetermined),
        "unresolved": sum(row["status"] == "unresolved" for row in rows),
        "largest_width": max((row["width"] for row in rows if "width" in row), default=0.0),
        "largest_undetermined_width": max((row["anchored_width"] for row in undetermined), default=0.0),
    }
    if keep_all:
        summary["rows"] = rows
    else:
        summary["widest"] = sorted(undetermined, key=lambda row: -row["anchored_width"])[:EXAMPLES]
    return summary


def binding_structure(model, solution, cells: list[dict]) -> dict:
    """Per claimant: cells binding in every optimal plan, in some, and in the reported plan."""

    by_label = {row["quantity"]: row for row in cells}
    out = {}
    for claimant in model.claimants:
        guarantee = solution.guarantees[claimant]
        every, some, reported, unresolved = [], [], [], []
        for scenario, period in positive_cells(model, claimant):
            row = by_label[f"{scenario}|{period}|{claimant}"]
            label = f"{scenario}|{period}"
            if abs(row["published"] - guarantee) <= BINDING:
                reported.append(label)
            if row["status"] == "unresolved":
                unresolved.append(label)
            elif row["status"] == "undetermined":
                if row["anchored_minimum"] <= guarantee + BINDING:
                    some.append(label)
            elif abs(row["published"] - guarantee) <= BINDING:
                every.append(label)
        out[claimant] = {
            "guarantee": guarantee,
            "binding_in_every_optimal_plan": every,
            "binding_in_some_optimal_plans_only": some,
            "binding_in_the_reported_plan": reported,
            "unresolved_cells": unresolved,
        }
    return out


def efficiency_range(families: dict[str, dict]) -> dict:
    delivery = {row["quantity"]: row for row in families["scenario_beneficial_delivery_af"]["rows"]}
    injection = {row["quantity"]: row for row in families["scenario_source_injection_af"]["rows"]}
    out = {}
    for scenario, row in delivery.items():
        source = injection[scenario]
        out[scenario] = {"published": row["published"] / source["published"]}
        if "minimum" in row and "minimum" in source:
            out[scenario].update({"minimum": row["minimum"] / source["maximum"],
                                  "maximum": row["maximum"] / source["minimum"]})
    return out


# --------------------------------------------------------------------------------------
# Comparators


def comparator_report(model, rule: str, solver, lexicographic, *, most_favorable: bool) -> dict:
    solution = solver(model)
    level = solution.leximin_levels[0].level
    fixed = {claimant: level for claimant in model.claimants}
    rows = preserved_rows(model, solution)
    face = Face(model, fixed, rows)
    anchored = None
    claimants = {}
    for claimant in model.claimants:
        cells = [cell_coefficients(model, s, p, claimant) for s, p in positive_cells(model, claimant)]
        row = {"realized_in_the_reported_plan": solution.guarantees[claimant]}
        claimants[claimant] = row
        try:
            row["realized_minimum_over_the_face"] = min(face.minimum(face.vector(c)) for c in cells)
            row["realized_maximum_over_the_face"] = face.largest_floor(cells)
        except OptimizationError as error:
            row.update({"status": "unresolved", "error": str(error)})
            continue
        if row["realized_maximum_over_the_face"] - row["realized_minimum_over_the_face"] <= DETERMINED:
            row["status"] = "determined"
            continue
        try:
            if anchored is None:
                anchored = Face(model, fixed, anchored_rows(model, fixed, rows)[0])
            row["anchored_minimum"] = min(anchored.minimum(anchored.vector(c)) for c in cells)
            row["anchored_maximum"] = anchored.largest_floor(cells)
        except OptimizationError as error:
            row.update({"status": "unresolved", "error": f"anchored face: {error}"})
            continue
        row["status"] = ("determined_up_to_preservation_tolerance"
                         if row["anchored_maximum"] - row["anchored_minimum"] <= DETERMINED else "undetermined")
    best, how = leximin_best(model, rows) if most_favorable else (None, {"not computed": True})
    scenarios = {}
    for scenario in model.scenarios:
        coefficients = {("x", scenario, p, t.terminal_id): 1.0 for p in model.periods for t in model.terminals}
        published = sum(v for k, v in solution.beneficial_delivery.items() if k[0] == scenario)
        try:
            low, high = face.extremes(coefficients)
        except OptimizationError as error:
            scenarios[scenario] = {"published": published, "determined": None, "error": str(error)}
            continue
        scenarios[scenario] = {
            "published": published, "minimum": low, "maximum": high,
            "determined": scaled(high - low, published, "volume", solution.nominal_beneficial_delivery) <= DETERMINED,
        }

    # Is the CTI-RLex plan one of this rule's optimal plans?
    x = np.zeros(len(face.problem.keys))
    for key, idx in face.problem.index.items():
        family = key[0]
        if family == "x":
            x[idx] = lexicographic.beneficial_delivery[key[1:]]
        elif family == "w":
            x[idx] = lexicographic.gross_terminal_withdrawal[key[1:]]
        elif family == "g":
            x[idx] = lexicographic.source_injection[key[1:]]
        elif family == "q":
            x[idx] = lexicographic.edge_flow[key[1:]]
        elif family == "rho":
            x[idx] = level
    # u is not carried by the solution; the smallest admissible value is |contingency - nominal|.
    for key, idx in face.problem.index.items():
        if key[0] == "u":
            asset = model.control_by_id[key[3]]
            prefix = "g" if asset.resource_type == "source" else "q"
            a = x[face.problem.index[(prefix, key[1], key[2], asset.resource_id)]]
            b = x[face.problem.index[(prefix, model.nominal_scenario, key[2], asset.resource_id)]]
            x[idx] = abs(a - b)
    violation = max(
        float(np.max(face.problem.a_ub @ x - face.problem.b_ub, initial=0.0)),
        float(np.max(np.abs(face.problem.a_eq @ x - face.problem.b_eq), initial=0.0)),
    )
    sorted_published = sorted(solution.guarantees.values())
    return {
        "rule": rule,
        "face_program_fallbacks": {"face": face.fallbacks, "anchored_face": None if anchored is None else anchored.fallbacks},
        "common_floor": level,
        "nominal_delivery_af": solution.nominal_beneficial_delivery,
        "claimants": claimants,
        "realized_sorted_in_the_reported_plan": sorted_published,
        "most_favorable_sorted_vector_on_the_face": None if best is None else sorted(best.values()),
        "most_favorable_vector_on_the_face": best,
        "most_favorable_vector_fallbacks": how.get("fallbacks", how),
        "most_favorable_vector_blocking_tolerance": how.get("blocking_tolerance"),
        "most_favorable_vector_errors": how.get("errors", {}),
        "every_realized_guarantee_is_determined": all(
            row["status"] in ("determined", "determined_up_to_preservation_tolerance") for row in claimants.values()
        ),
        "undetermined_realized_guarantees": sorted(c for c, row in claimants.items() if row["status"] == "undetermined"),
        "unresolved_realized_guarantees": sorted(c for c, row in claimants.items() if row["status"] == "unresolved"),
        "scenario_beneficial_delivery_af": scenarios,
        "the_cti_rlex_plan_is_one_of_its_optimal_plans": violation <= 1e-6,
        "largest_violation_of_its_face_by_the_cti_rlex_plan": violation,
    }


# --------------------------------------------------------------------------------------
# Reproducibility


def plan_values(solution) -> dict:
    values = {}
    for name in ("edge_flow", "source_injection", "gross_terminal_withdrawal", "beneficial_delivery",
                 "period_service_ratio", "seasonal_service_ratio", "recourse_by_scenario", "guarantees"):
        for key, value in getattr(solution, name).items():
            values[name, key] = value
    return values


def reproducibility(model, solution, families: dict[str, list[Quantity]], status: dict[str, str]) -> dict:
    repeat = solve_cti_rlex(model)
    first, second = plan_values(solution), plan_values(repeat)
    identical = first.keys() == second.keys() and all(first[key] == second[key] for key in first)

    saved = HIGHS_OPTIONS["presolve"]
    lp_module.HIGHS_OPTIONS["presolve"] = False
    try:
        other = solve_cti_rlex(model)
    finally:
        lp_module.HIGHS_OPTIONS["presolve"] = saved

    kinds = ("determined", "determined_up_to_preservation_tolerance", "undetermined", "unresolved")
    change = {kind: 0.0 for kind in kinds}
    moved = {kind: 0 for kind in kinds}
    for family, items in families.items():
        if family not in REPORTED:
            continue
        for label, _coefficients, value_of in items:
            kind = status[family, label]
            difference = scaled(abs(value_of(other) - value_of(solution)), value_of(solution), UNIT[family],
                                solution.nominal_beneficial_delivery)
            change[kind] = max(change[kind], difference)
            moved[kind] += difference > DETERMINED
    return {
        "repeated_solve_is_identical_value_for_value": identical,
        "presolve_off": {
            "guarantee_max_change": max(abs(other.guarantees[c] - solution.guarantees[c]) for c in model.claimants),
            "nominal_delivery_change_af": other.nominal_beneficial_delivery - solution.nominal_beneficial_delivery,
            "weighted_contingency_delivery_change_af":
                other.weighted_contingency_beneficial_delivery - solution.weighted_contingency_beneficial_delivery,
            "recourse_effort_change": other.normalized_recourse_effort - solution.normalized_recourse_effort,
            "largest_scaled_change_by_status": change,
            "reported_quantities_that_moved_by_status": moved,
        },
    }


# --------------------------------------------------------------------------------------


def main() -> None:
    report = {
        "preservation_tolerance": PRESERVATION,
        "determined_threshold": DETERMINED,
        "binding_tolerance": BINDING,
        "reported_families": list(REPORTED),
        "instances": {},
    }
    for name, path in INSTANCES.items():
        started = time.perf_counter()
        model = load_cti_benchmark(path)
        solution = solve_cti_rlex(model)
        rows = preserved_rows(model, solution)
        face = Face(model, solution.guarantees, rows)
        anchor_rows, anchors = anchored_rows(model, solution.guarantees, rows)
        anchored = Face(model, solution.guarantees, anchor_rows)

        families = cti_quantities(model, name)
        measured = {family: measure(face, anchored, solution, items, UNIT[family]) for family, items in families.items()}
        status = {(family, row["quantity"]): row["status"] for family, rows_ in measured.items() for row in rows_}
        summary = {family: summarize(rows_, keep_all=family in REPORTED) for family, rows_ in measured.items()}
        for family, item in summary.items():
            print(f"{name:16s} {family:34s} {item['quantities']:4d} quantities: {item['determined']:4d} determined, "
                  f"{item['determined_up_to_preservation_tolerance']:3d} up to the tolerance, "
                  f"{item['undetermined']:4d} undetermined (widest {item['largest_undetermined_width']:.4g})"
                  + (f", {item['unresolved']} UNRESOLVED" if item["unresolved"] else ""))

        realized = {}
        by_label = {row["quantity"]: row for row in measured["period_service_ratio"]}
        for claimant in model.claimants:
            cells = positive_cells(model, claimant)
            labels = [f"{scenario}|{period}|{claimant}" for scenario, period in cells]
            row = {
                "guarantee": solution.guarantees[claimant],
                "realized_in_the_reported_plan": min(by_label[label]["published"] for label in labels),
            }
            realized[claimant] = row
            if any("minimum" not in by_label[label] for label in labels):
                row["status"] = "unresolved"
                continue
            row["realized_minimum_over_the_face"] = min(by_label[label]["minimum"] for label in labels)
            try:
                row["realized_maximum_over_the_face"] = face.largest_floor(
                    [cell_coefficients(model, scenario, period, claimant) for scenario, period in cells]
                )
            except OptimizationError as error:
                row.update({"status": "unresolved", "error": str(error)})
                continue
            row["status"] = "measured"
        every_plan_realizes_the_vector = all(
            row["status"] == "measured"
            and abs(row["realized_minimum_over_the_face"] - row["guarantee"]) <= DETERMINED
            and abs(row["realized_maximum_over_the_face"] - row["guarantee"]) <= DETERMINED
            for row in realized.values()
        )
        print(f"{name}: every optimal plan realizes the guarantee vector: {every_plan_realizes_the_vector}")

        entry = {
            "benchmark_id": model.benchmark_id,
            "anchors": anchors,
            "face_program_fallbacks": {"face": face.fallbacks, "anchored_face": anchored.fallbacks},
            "stage_optima": {
                "nominal_delivery_af": solution.nominal_beneficial_delivery,
                "weighted_contingency_delivery_af": solution.weighted_contingency_beneficial_delivery,
                "recourse_effort": solution.normalized_recourse_effort,
            },
            "cti_rlex": {
                "guarantees": dict(solution.guarantees),
                "realized_guarantees": realized,
                "every_optimal_plan_realizes_the_guarantee_vector": every_plan_realizes_the_vector,
                "families": summary,
                "end_to_end_efficiency": efficiency_range(summary),
                "binding": binding_structure(model, solution, measured["period_service_ratio"]),
                "every_reported_quantity_is_determined": all(
                    summary[family]["undetermined"] == 0 and summary[family]["unresolved"] == 0 for family in REPORTED
                ),
                "unresolved_quantities": sum(summary[family]["unresolved"] for family in summary),
            },
        }
        entry["reproducibility"] = reproducibility(model, solution, families, status)
        print(f"{name}: repeated solve identical: {entry['reproducibility']['repeated_solve_is_identical_value_for_value']}; "
              f"presolve off: {entry['reproducibility']['presolve_off']['largest_scaled_change_by_status']}")
        entry["comparators"] = {
            "PROP-BR": comparator_report(model, "PROP-BR", solve_robust_proportional, solution, most_favorable=True),
            "UTIL-BR": comparator_report(model, "UTIL-BR", solve_utilitarian_fair, solution, most_favorable=False),
        }
        for rule, item in entry["comparators"].items():
            best = item["most_favorable_sorted_vector_on_the_face"]
            print(f"{name}: {rule} realized guarantees determined: {item['every_realized_guarantee_is_determined']}; "
                  f"most favorable sorted vector on its face (fallbacks {item['most_favorable_vector_fallbacks']}, "
                  f"blocking tolerance {item['most_favorable_vector_blocking_tolerance']}): "
                  f"{None if best is None else [round(v, 4) for v in best]}; "
                  f"CTI-RLex plan is one of its optimal plans: {item['the_cti_rlex_plan_is_one_of_its_optimal_plans']}")
        print(f"{name}: fallbacks on the face {face.fallbacks}, on the anchored face {anchored.fallbacks}")
        entry["seconds"] = round(time.perf_counter() - started, 1)
        report["instances"][name] = entry
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
