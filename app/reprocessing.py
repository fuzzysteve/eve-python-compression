from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

STANDING_TAX_FULL_WAIVER = 6.67
STANDING_TAX_MAX_RATE = 0.05


class StructureBonus(str, Enum):
    STANDARD = "standard"
    ATHANOR = "athanor"
    TATARA = "tatara"


class SecurityBonus(str, Enum):
    HIGH_SEC = "high_sec"
    LOW_SEC = "low_sec"
    NULL_SEC = "null_sec"


_STRUCTURE_BONUS_VALUES: dict[StructureBonus, float] = {
    StructureBonus.STANDARD: 0.0,
    StructureBonus.ATHANOR: 0.02,
    StructureBonus.TATARA: 0.055,
}

_SECURITY_BONUS_VALUES: dict[SecurityBonus, float] = {
    SecurityBonus.HIGH_SEC: 0.0,
    SecurityBonus.LOW_SEC: 0.06,
    SecurityBonus.NULL_SEC: 0.12,
}


class NpcStationLocation(BaseModel):
    type: Literal["npc_station"] = "npc_station"
    base_yield: float = Field(ge=0, le=1, description="Station base reprocessing yield, e.g. 0.5 for 50%")
    standing: float = Field(default=0.0, ge=0, description="Effective standing with the station owner, for reprocessing tax")


class StructureLocation(BaseModel):
    type: Literal["structure"] = "structure"
    structure_bonus: StructureBonus = StructureBonus.STANDARD
    rig_tier: Literal[0, 1, 3] = 0
    security: SecurityBonus = SecurityBonus.HIGH_SEC


Location = NpcStationLocation | StructureLocation


class ReprocessingInputs(BaseModel):
    reprocessing_skill: int = Field(default=0, ge=0, le=5)
    reprocessing_efficiency_skill: int = Field(default=0, ge=0, le=5)
    ore_processing_skills: dict[int, Annotated[int, Field(ge=0, le=5)]] = Field(
        default_factory=dict, description="skillTypeID -> level (0-5)"
    )
    implant_bonus: float = Field(default=0.0)
    location: Location = Field(discriminator="type")


def _standing_tax_rate(standing: float) -> float:
    if standing >= STANDING_TAX_FULL_WAIVER:
        return 0.0
    return STANDING_TAX_MAX_RATE * (STANDING_TAX_FULL_WAIVER - standing) / STANDING_TAX_FULL_WAIVER


def ore_yield_multiplier(skill_type_id: int | None, reprocessing: ReprocessingInputs) -> float:
    op_level = reprocessing.ore_processing_skills.get(skill_type_id, 0) if skill_type_id is not None else 0

    skill_multiplier = (
        (1 + reprocessing.reprocessing_skill * 0.03)
        * (1 + reprocessing.reprocessing_efficiency_skill * 0.02)
        * (1 + op_level * 0.02)
        * (1 + reprocessing.implant_bonus)
    )

    location = reprocessing.location
    if location.type == "npc_station":
        yield_fraction = location.base_yield * skill_multiplier
        yield_fraction *= 1 - _standing_tax_rate(location.standing)
        return yield_fraction

    security_bonus = _SECURITY_BONUS_VALUES[location.security] if location.rig_tier > 0 else 0.0
    structure_bonus = _STRUCTURE_BONUS_VALUES[location.structure_bonus]
    base_yield = (50 + location.rig_tier) / 100
    return base_yield * (1 + security_bonus) * (1 + structure_bonus) * skill_multiplier
