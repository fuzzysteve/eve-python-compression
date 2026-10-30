import random
from importlib.metadata import version
from types import SimpleNamespace

import numpy as np
import pulp
import pytest

from app import optimizer
from app.optimizer import InfeasibleError, TooComplexError, solve_purchase_list
from tests.conftest import HEAVY_WATER, MEXALLON, PYERITE, TRITANIUM, inputs, ore


def solve(ores, required, allowed=None, overage=None, reprocessing=None):
    return solve_purchase_list(ores, required, allowed, overage, reprocessing or inputs())


def by_ore(result):
    return {line.ore_type_id: line.quantity for line in result.purchase_list}


def test_quantity_is_whole_portions_and_volume_is_per_unit():
    result = solve({1: ore(1, volume=0.5, m34=400)}, {TRITANIUM: 1000})
    assert by_ore(result) == {1: 300}  # 3 batches of 100
    assert result.purchase_list[0].volume_m3 == pytest.approx(150)
    assert result.total_volume_m3 == pytest.approx(150)
    assert result.mineral_totals == {TRITANIUM: 1200}


def test_portion_size_is_read_from_the_ore_not_assumed_to_be_100():
    # Ice and gas are portionSize 1; invTypeMaterials is per portion either way.
    result = solve({1: ore(1, volume=1000.0, portion=1, m16272=10)}, {HEAVY_WATER: 25})
    assert by_ore(result) == {1: 3}
    assert result.total_volume_m3 == pytest.approx(3000)
    assert result.mineral_totals == {HEAVY_WATER: 30}


def test_mixed_portion_sizes_in_one_solve():
    ores = {1: ore(1, volume=0.1, portion=100, m34=100), 2: ore(2, volume=5.0, portion=1, m16272=10)}
    result = solve(ores, {TRITANIUM: 100, HEAVY_WATER: 10})
    assert by_ore(result) == {1: 100, 2: 1}
    assert result.total_volume_m3 == pytest.approx(10 + 5)


def test_minimises_volume_not_ore_count():
    # One batch of ore 1 is 100 m3; the ten batches of ore 2 it replaces are 90 m3.
    ores = {1: ore(1, volume=1.0, m34=1000), 2: ore(2, volume=0.09, m34=100)}
    assert by_ore(solve(ores, {TRITANIUM: 1000})) == {2: 1000}


def test_combines_ores_when_that_is_smaller():
    # One batch each of ores 1 and 2 is 2 m3; the all-rounder would need 7 batches, 35 m3.
    ores = {
        1: ore(1, volume=0.01, m34=700),
        2: ore(2, volume=0.01, m35=700),
        3: ore(3, volume=0.05, m34=100, m35=100),
    }
    assert by_ore(solve(ores, {TRITANIUM: 700, PYERITE: 700})) == {1: 100, 2: 100}


def test_output_is_floored_per_batch_not_on_the_total():
    # 7 * 0.5 = 3.5 floors to 3 a batch, so two batches give 6, not 7.
    result = solve({1: ore(1, m34=7)}, {TRITANIUM: 7}, reprocessing=inputs(0.5))
    assert by_ore(result) == {1: 300}
    assert result.mineral_totals == {TRITANIUM: 9}


def test_float_error_does_not_lose_a_mineral_to_flooring():
    assert 100 * 0.29 < 29  # the case the epsilon in solve_purchase_list exists for
    result = solve({1: ore(1, m34=100)}, {TRITANIUM: 29}, reprocessing=inputs(0.29))
    assert by_ore(result) == {1: 100}
    assert result.mineral_totals == {TRITANIUM: 29}


def test_mineral_totals_are_ints_and_cover_only_what_was_required():
    result = solve({1: ore(1, m34=400, m35=200)}, {TRITANIUM: 400})
    assert result.mineral_totals == {TRITANIUM: 400}
    assert all(type(v) is int for v in result.mineral_totals.values())


def test_a_required_mineral_met_by_two_ores_is_summed():
    ores = {1: ore(1, volume=0.01, m34=300, m35=500), 2: ore(2, volume=0.01, m34=300, m36=500)}
    result = solve(ores, {TRITANIUM: 600, PYERITE: 500, MEXALLON: 500})
    assert result.mineral_totals == {TRITANIUM: 600, PYERITE: 500, MEXALLON: 500}


def test_unused_ores_are_left_off_the_list():
    ores = {1: ore(1, m34=100), 2: ore(2, m36=100)}
    assert set(by_ore(solve(ores, {TRITANIUM: 100}))) == {1}


def test_no_required_minerals_buys_nothing():
    result = solve({1: ore(1, m34=100)}, {})
    assert result.purchase_list == []
    assert result.total_volume_m3 == 0
    assert result.mineral_totals == {}


def test_a_requirement_of_zero_buys_nothing():
    result = solve({1: ore(1, m34=100)}, {TRITANIUM: 0})
    assert result.purchase_list == []
    assert result.mineral_totals == {TRITANIUM: 0}


def test_allowed_ores_excludes_the_better_ore():
    ores = {1: ore(1, volume=0.01, m34=100), 2: ore(2, volume=1.0, m34=100)}
    assert by_ore(solve(ores, {TRITANIUM: 100}, allowed=[2])) == {2: 100}


def test_duplicate_allowed_ores_are_harmless():
    assert by_ore(solve({1: ore(1, m34=100)}, {TRITANIUM: 100}, allowed=[1, 1])) == {1: 100}


def test_unknown_allowed_ore_is_named():
    with pytest.raises(InfeasibleError, match=r"Unknown ore type ID\(s\): 8, 9"):
        solve({1: ore(1, m34=100)}, {TRITANIUM: 1}, allowed=[9, 1, 8])


def test_mineral_no_candidate_yields_is_named():
    with pytest.raises(InfeasibleError, match="No candidate ore yields .*: 35"):
        solve({1: ore(1, m34=100)}, {PYERITE: 1})


def test_mineral_only_a_disallowed_ore_yields_is_rejected():
    ores = {1: ore(1, m34=100), 2: ore(2, m35=100)}
    with pytest.raises(InfeasibleError, match="No candidate ore yields"):
        solve(ores, {PYERITE: 1}, allowed=[1])


def test_empty_allowed_ores_cannot_meet_a_requirement():
    with pytest.raises(InfeasibleError):
        solve({1: ore(1, m34=100)}, {TRITANIUM: 1}, allowed=[])


def test_yield_that_floors_to_zero_is_infeasible():
    with pytest.raises(InfeasibleError, match="No combination"):
        solve({1: ore(1, m34=1)}, {TRITANIUM: 1}, reprocessing=inputs(0.5))


def test_overage_is_a_fraction_of_the_requirement():
    ores = {1: ore(1, m34=400)}
    assert by_ore(solve(ores, {TRITANIUM: 1000}, overage={TRITANIUM: 0.2})) == {1: 300}
    with pytest.raises(InfeasibleError, match="No combination"):
        solve(ores, {TRITANIUM: 1000}, overage={TRITANIUM: 0.19})


def test_zero_overage_needs_an_exact_hit():
    ores = {1: ore(1, m34=400)}
    assert by_ore(solve(ores, {TRITANIUM: 800}, overage={TRITANIUM: 0})) == {1: 200}


def test_overage_steers_the_solve_to_a_larger_ore():
    ores = {1: ore(1, volume=0.01, m34=1000, m35=100), 2: ore(2, volume=1.0, m34=100, m35=100)}
    required = {TRITANIUM: 100, PYERITE: 100}
    assert by_ore(solve(ores, required)) == {1: 100}
    assert by_ore(solve(ores, required, overage={TRITANIUM: 0.5})) == {2: 100}


def test_overage_is_per_mineral():
    ores = {1: ore(1, m34=100, m35=1000)}
    result = solve(ores, {TRITANIUM: 100, PYERITE: 100}, overage={TRITANIUM: 0})
    assert result.mineral_totals == {TRITANIUM: 100, PYERITE: 1000}


def test_time_limit_is_rejected_as_too_complex(monkeypatch):
    stats = SimpleNamespace(status=pulp.LpSolveStatus.TimeLimit)
    monkeypatch.setattr(pulp.LpProblem, "solve", lambda self, solver=None: stats)
    with pytest.raises(TooComplexError, match="10 seconds"):
        solve({1: ore(1, m34=100)}, {TRITANIUM: 1})


def test_solves_with_the_time_limit(monkeypatch):
    seen = {}
    real = pulp.COIN_CMD

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(optimizer.pulp, "COIN_CMD", spy)
    solve({1: ore(1, m34=100)}, {TRITANIUM: 1})
    assert seen["timeLimit"] == optimizer.SOLVE_TIME_LIMIT_SECONDS


def test_matches_brute_force():
    """Exhaustive search over small problems, with and without overage caps: CBC must find
    the same minimum, and report infeasible exactly when there is no answer. Requirements
    stay at or below MAX_BATCHES, and a useful batch yields at least 1, so the grid can't
    miss the optimum."""
    MAX_BATCHES = 30
    grid = np.indices((MAX_BATCHES + 1,) * 3).reshape(3, -1)
    rng = random.Random(20261030)
    for _ in range(60):
        ores = {
            i: ore(i, volume=rng.choice([0.01, 0.1, 0.3, 1.0]), portion=rng.choice([1, 100]),
                   m34=rng.randint(0, 50), m35=rng.randint(0, 50))
            for i in range(3)
        }
        required = {TRITANIUM: rng.randint(1, MAX_BATCHES), PYERITE: rng.randint(1, MAX_BATCHES)}
        overage = {TRITANIUM: rng.choice([0.1, 0.5])} if rng.random() < 0.5 else None
        multiplier = rng.choice([0.5, 0.73])

        totals = {
            mineral: sum(int(ores[i].base_yields[mineral] * multiplier) * grid[i] for i in ores)
            for mineral in required
        }
        feasible = (totals[TRITANIUM] >= required[TRITANIUM]) & (totals[PYERITE] >= required[PYERITE])
        if overage:
            feasible &= totals[TRITANIUM] <= required[TRITANIUM] * (1 + overage[TRITANIUM])
        volumes = sum(ores[i].portion_size * ores[i].volume_m3 * grid[i] for i in ores)

        if not feasible.any():
            with pytest.raises(InfeasibleError):
                solve(ores, required, overage=overage, reprocessing=inputs(multiplier))
            continue
        result = solve(ores, required, overage=overage, reprocessing=inputs(multiplier))
        assert result.total_volume_m3 == pytest.approx(volumes[feasible].min())


def test_cbcbox_stays_below_the_version_that_misreports_infeasible():
    # See CLAUDE.md before changing this: 2.931+ wrongly rejected a feasible request.
    major, minor = version("cbcbox").split(".")[:2]
    assert (int(major), int(minor)) < (2, 931)
