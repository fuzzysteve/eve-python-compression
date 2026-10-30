import pytest
from pydantic import ValidationError

from app.reprocessing import ReprocessingInputs, _standing_tax_rate, ore_yield_multiplier
from tests.conftest import SKILL_A, SKILL_B


def station(base_yield=0.5, standing=6.67, **kwargs):
    return ReprocessingInputs(
        location={"type": "npc_station", "base_yield": base_yield, "standing": standing}, **kwargs
    )


def structure(rig_tier=0, security="high_sec", structure_bonus="standard", **kwargs):
    return ReprocessingInputs(
        location={
            "type": "structure",
            "rig_tier": rig_tier,
            "security": security,
            "structure_bonus": structure_bonus,
        },
        **kwargs,
    )


@pytest.mark.parametrize(
    "standing, rate",
    [
        (0, 0.05),
        (3.335, 0.025),
        (6.67, 0.0),
        (10, 0.0),
    ],
)
def test_standing_tax_is_linear_down_to_the_waiver(standing, rate):
    assert _standing_tax_rate(standing) == pytest.approx(rate)


def test_npc_station_no_skills_full_standing_is_the_base_yield():
    assert ore_yield_multiplier(SKILL_A, station(0.5)) == pytest.approx(0.5)


def test_npc_station_applies_standings_tax():
    assert ore_yield_multiplier(SKILL_A, station(0.5, standing=0)) == pytest.approx(0.5 * 0.95)


def test_skills_multiply_rather_than_add():
    reprocessing = station(
        reprocessing_skill=5,
        reprocessing_efficiency_skill=5,
        ore_processing_skills={SKILL_A: 5},
        implant_bonus=0.04,
    )
    assert ore_yield_multiplier(SKILL_A, reprocessing) == pytest.approx(0.5 * 1.15 * 1.10 * 1.10 * 1.04)


def test_only_the_ores_own_processing_skill_counts():
    reprocessing = station(ore_processing_skills={SKILL_B: 5})
    assert ore_yield_multiplier(SKILL_A, reprocessing) == pytest.approx(0.5)
    assert ore_yield_multiplier(SKILL_B, reprocessing) == pytest.approx(0.5 * 1.10)


def test_ore_with_no_processing_skill_ignores_the_skill_map():
    reprocessing = station(ore_processing_skills={SKILL_A: 5})
    assert ore_yield_multiplier(None, reprocessing) == pytest.approx(0.5)


def test_structure_defaults_to_50_percent_with_no_rig():
    assert ore_yield_multiplier(SKILL_A, structure()) == pytest.approx(0.50)


@pytest.mark.parametrize(
    "rig_tier, security, expected",
    [
        (1, "high_sec", 0.51),
        (3, "high_sec", 0.53),
        (1, "low_sec", 0.51 * 1.06),
        (3, "low_sec", 0.53 * 1.06),
        (1, "null_sec", 0.51 * 1.12),
        (3, "null_sec", 0.53 * 1.12),
    ],
)
def test_structure_rig_and_security(rig_tier, security, expected):
    assert ore_yield_multiplier(SKILL_A, structure(rig_tier, security)) == pytest.approx(expected)


def test_security_bonus_needs_a_rig():
    assert ore_yield_multiplier(SKILL_A, structure(0, "null_sec")) == pytest.approx(0.50)


@pytest.mark.parametrize(
    "bonus, expected",
    [("standard", 0.53), ("athanor", 0.53 * 1.02), ("tatara", 0.53 * 1.055)],
)
def test_structure_type_bonus(bonus, expected):
    assert ore_yield_multiplier(SKILL_A, structure(3, structure_bonus=bonus)) == pytest.approx(expected)


def test_structure_bonus_applies_without_a_rig():
    assert ore_yield_multiplier(SKILL_A, structure(0, structure_bonus="tatara")) == pytest.approx(0.50 * 1.055)


def test_structures_pay_no_standings_tax_and_still_take_skills():
    reprocessing = structure(3, reprocessing_skill=5)
    assert ore_yield_multiplier(SKILL_A, reprocessing) == pytest.approx(0.53 * 1.15)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reprocessing_skill": 6},
        {"reprocessing_skill": -1},
        {"reprocessing_efficiency_skill": 6},
    ],
)
def test_skill_levels_are_bounded(kwargs):
    with pytest.raises(ValidationError):
        station(**kwargs)


@pytest.mark.parametrize("base_yield", [-0.1, 1.1])
def test_base_yield_must_be_a_fraction(base_yield):
    with pytest.raises(ValidationError):
        station(base_yield)


def test_negative_standing_is_rejected():
    with pytest.raises(ValidationError):
        station(standing=-1)


def test_rig_tier_2_does_not_exist():
    with pytest.raises(ValidationError):
        structure(2)


def test_unknown_location_type_is_rejected():
    with pytest.raises(ValidationError):
        ReprocessingInputs(location={"type": "citadel"})


@pytest.mark.parametrize("level", [6, -1])
def test_ore_processing_skill_levels_are_bounded(level):
    with pytest.raises(ValidationError):
        station(ore_processing_skills={SKILL_A: level})


@pytest.mark.parametrize("level", [0, 5])
def test_ore_processing_skill_level_limits_are_allowed(level):
    assert station(ore_processing_skills={SKILL_A: level}).ore_processing_skills == {SKILL_A: level}
