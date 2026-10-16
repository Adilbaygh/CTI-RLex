"""Structure of the two analyses added in October 2026: larger canal losses (Reviewer 2) and
PRIOR-LEX with tiers assigned to rights (Reviewer 1, point 2.1). No linear program is solved."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from leximin.dag import load_cti_benchmark

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import conveyance_loss_levels as losses  # noqa: E402
import prior_lex  # noqa: E402
import prior_lex_rights as rights  # noqa: E402

LITTLE_BEAR = ROOT / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"
CACHE_VALLEY = ROOT / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json"


def test_canal_losses_scale_only_canal_reaches() -> None:
    payload = json.loads(LITTLE_BEAR.read_text(encoding="utf-8"))
    model = load_cti_benchmark(LITTLE_BEAR)
    canals = losses.canal_edges(payload, model)
    assert len(canals) == 9
    same = losses.with_canal_losses(model, canals, 1)
    assert dict(same.edge_efficiency) == dict(model.edge_efficiency)
    doubled = losses.with_canal_losses(model, canals, 2)
    for key, eta in model.edge_efficiency.items():
        expected = eta ** 2 if key[2] in canals else eta
        assert doubled.edge_efficiency[key] == pytest.approx(expected, abs=1e-15)


@pytest.fixture(scope="module")
def wellsville_split():
    points, _ = prior_lex.decree_records()
    payload = json.loads(CACHE_VALLEY.read_text(encoding="utf-8"))
    model = load_cti_benchmark(CACHE_VALLEY)
    table = prior_lex.tier_table(payload, model, points)
    row = next(item for item in table if item["claimant"] == "company_162")
    parts, _ = rights.demand_parts(payload, model, row)
    split = rights.split_model(model, {"company_162": parts})
    return model, table, parts, split


def test_the_parts_add_up_to_the_claimant_demand(wellsville_split) -> None:
    model, _, parts, split = wellsville_split
    for period in model.periods:
        total = sum(split.demand[period, f"company_162#{part}"] for part in parts)
        assert total == pytest.approx(model.demand[period, "company_162"], abs=1e-9)
    assert "company_162" not in split.claimants


def test_every_part_is_served_where_the_claimant_was(wellsville_split) -> None:
    model, _, parts, split = wellsville_split
    original = model.terminals_by_claimant["company_162"]
    for part in parts:
        copies = split.terminals_by_claimant[f"company_162#{part}"]
        assert {terminal.node for terminal in copies} == {terminal.node for terminal in original}
        for copy, terminal in zip(copies, original):
            for period in model.periods:
                assert split.application_efficiency[period, copy.terminal_id] == \
                    model.application_efficiency[period, terminal.terminal_id]


def test_the_storage_part_ranks_after_every_decreed_year(wellsville_split) -> None:
    _, table, parts, split = wellsville_split
    tiers = rights.right_tiers(table, split.claimants, {"company_162": parts})
    assert "company_162#storage" in tiers[-1]
    assert "company_162#1860" in tiers[0]
    assert "company_132" in tiers[-1]
