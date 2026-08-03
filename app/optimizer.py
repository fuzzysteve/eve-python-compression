import math
from dataclasses import dataclass

import pulp

from app.reprocessing import ReprocessingInputs, ore_yield_multiplier
from app.sde import OreData


class InfeasibleError(Exception):
    pass


@dataclass
class PurchaseLine:
    ore_type_id: int
    quantity: int
    volume_m3: float


@dataclass
class PurchaseResult:
    purchase_list: list[PurchaseLine]
    total_volume_m3: float
    mineral_totals: dict[int, int]


def solve_purchase_list(
    ores: dict[int, OreData],
    required_minerals: dict[int, float],
    allowed_ores: list[int] | None,
    overage: dict[int, float] | None,
    reprocessing: ReprocessingInputs,
) -> PurchaseResult:
    if allowed_ores is not None:
        unknown = set(allowed_ores) - set(ores)
        if unknown:
            raise InfeasibleError(f"Unknown ore type ID(s): {', '.join(str(t) for t in sorted(unknown))}")
        candidate_ores = {type_id: ores[type_id] for type_id in allowed_ores}
    else:
        candidate_ores = ores

    unknown_minerals = set(required_minerals) - {
        mineral for ore in candidate_ores.values() for mineral in ore.base_yields
    }
    if unknown_minerals:
        raise InfeasibleError(
            f"No candidate ore yields the following mineral type ID(s): "
            f"{', '.join(str(m) for m in sorted(unknown_minerals))}"
        )

    effective_yields: dict[int, dict[int, float]] = {}
    for type_id, ore in candidate_ores.items():
        multiplier = ore_yield_multiplier(ore.skill_type_id, reprocessing)
        effective_yields[type_id] = {mineral: qty * multiplier for mineral, qty in ore.base_yields.items()}

    problem = pulp.LpProblem("compressed_ore_purchase", pulp.LpMinimize)

    batch_vars = {
        type_id: pulp.LpVariable(f"batches_{type_id}", lowBound=0, cat="Integer")
        for type_id in candidate_ores
    }

    problem += pulp.lpSum(
        candidate_ores[type_id].volume_m3 * candidate_ores[type_id].portion_size * batch_vars[type_id]
        for type_id in candidate_ores
    )

    overage = overage or {}
    for mineral, min_qty in required_minerals.items():
        total_output = pulp.lpSum(
            effective_yields[type_id].get(mineral, 0.0) * batch_vars[type_id] for type_id in candidate_ores
        )
        problem += total_output >= min_qty, f"min_{mineral}"

        if mineral in overage:
            max_qty = min_qty * (1 + overage[mineral])
            problem += total_output <= max_qty, f"max_{mineral}"

    status = problem.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[status] != "Optimal":
        raise InfeasibleError(
            "No combination of the allowed ores can satisfy the required minerals "
            "within the given overage limits."
        )

    purchase_list: list[PurchaseLine] = []
    raw_mineral_totals: dict[int, float] = {mineral: 0.0 for mineral in required_minerals}
    total_volume = 0.0

    for type_id, ore in candidate_ores.items():
        batches = round(batch_vars[type_id].value() or 0)
        if batches <= 0:
            continue
        quantity = batches * ore.portion_size
        volume = quantity * ore.volume_m3
        total_volume += volume
        purchase_list.append(PurchaseLine(ore_type_id=type_id, quantity=quantity, volume_m3=volume))

        for mineral, per_batch_qty in effective_yields[type_id].items():
            if mineral in raw_mineral_totals:
                raw_mineral_totals[mineral] += per_batch_qty * batches

    # EVE always truncates reprocessing output to a whole number of minerals - never fractional.
    # The tiny epsilon guards against float arithmetic landing just under a whole number
    # (e.g. 100188.0 computed as 100187.99999999997) and being floored down incorrectly.
    mineral_totals = {mineral: math.floor(qty + 1e-6) for mineral, qty in raw_mineral_totals.items()}

    return PurchaseResult(
        purchase_list=purchase_list,
        total_volume_m3=total_volume,
        mineral_totals=mineral_totals,
    )
