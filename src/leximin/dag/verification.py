from __future__ import annotations

from dataclasses import replace

from .domain import ClaimantTerminal, CTIBenchmark
from .solver import CTIRLexSolution, solve_cti_rlex


def split_terminal_record(
    model: CTIBenchmark,
    terminal_id: str,
    copies: int,
) -> CTIBenchmark:
    """Split a database terminal record without changing physical withdrawal access."""

    if copies < 2:
        raise ValueError("copies must be at least two.")
    original = next((item for item in model.terminals if item.terminal_id == terminal_id), None)
    if original is None:
        raise KeyError(terminal_id)
    replacements = tuple(
        ClaimantTerminal(
            terminal_id=f"{original.terminal_id}__split_{index}",
            claimant_id=original.claimant_id,
            node=original.node,
        )
        for index in range(1, copies + 1)
    )
    terminals = tuple(item for item in model.terminals if item.terminal_id != terminal_id) + replacements
    alpha = {
        key: value
        for key, value in model.application_efficiency.items()
        if key[1] != terminal_id
    }
    for period in model.periods:
        for item in replacements:
            alpha[period, item.terminal_id] = model.application_efficiency[period, terminal_id]
    return replace(model, terminals=terminals, application_efficiency=alpha)


def representation_invariance_error(
    model: CTIBenchmark,
    terminal_id: str,
    copies: int,
) -> tuple[float, CTIRLexSolution, CTIRLexSolution]:
    original = solve_cti_rlex(model)
    split = solve_cti_rlex(split_terminal_record(model, terminal_id, copies))
    error = max(abs(original.guarantees[item] - split.guarantees[item]) for item in model.claimants)
    return error, original, split
