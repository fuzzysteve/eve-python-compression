from dataclasses import dataclass

import pulp

from app.reprocessing import ReprocessingInputs, ore_yield_multiplier
from app.sde import OreData


class InfeasibleError(Exception):
    pass


@dataclass
class PurchaseLine:
    ore: str
    quantity: int
    volume_m3: float


@dataclass
class PurchaseResult:
    purchase_list: list[PurchaseLine]
    total_volume_m3: float
    mineral_totals: dict[str, float]


def solve_purchase_list(
    ores: dict[str, OreData],
    required_minerals: dict[str, float],
    allowed_ores: list[str] | None,
    overage: dict[str, float] | None,
    reprocessing: ReprocessingInputs,
) -> PurchaseResult:
    if allowed_ores is not None:
        unknown = set(allowed_ores) - set(ores)
        if unknown:
            raise InfeasibleError(f"Unknown ore name(s): {', '.join(sorted(unknown))}")
        candidate_ores = {name: ores[name] for name in allowed_ores}
    else:
        candidate_ores = ores

    unknown_minerals = set(required_minerals) - {
        mineral for ore in candidate_ores.values() for mineral in ore.base_yields
    }
    if unknown_minerals:
        raise InfeasibleError(
            f"No candidate ore yields the following mineral(s): {', '.join(sorted(unknown_minerals))}"
        )

    effective_yields: dict[str, dict[str, float]] = {}
    for name, ore in candidate_ores.items():
        multiplier = ore_yield_multiplier(ore.skill_type_id, reprocessing)
        effective_yields[name] = {mineral: qty * multiplier for mineral, qty in ore.base_yields.items()}

    problem = pulp.LpProblem("compressed_ore_purchase", pulp.LpMinimize)

    batch_vars = {
        name: pulp.LpVariable(f"batches_{ore.type_id}", lowBound=0, cat="Integer")
        for name, ore in candidate_ores.items()
    }

    problem += pulp.lpSum(
        candidate_ores[name].volume_m3 * 100 * batch_vars[name] for name in candidate_ores
    )

    overage = overage or {}
    for mineral, min_qty in required_minerals.items():
        total_output = pulp.lpSum(
            effective_yields[name].get(mineral, 0.0) * batch_vars[name] for name in candidate_ores
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
    mineral_totals: dict[str, float] = {mineral: 0.0 for mineral in required_minerals}
    total_volume = 0.0

    for name, ore in candidate_ores.items():
        batches = round(batch_vars[name].value() or 0)
        if batches <= 0:
            continue
        quantity = batches * 100
        volume = quantity * ore.volume_m3
        total_volume += volume
        purchase_list.append(PurchaseLine(ore=name, quantity=quantity, volume_m3=volume))

        for mineral, per_batch_qty in effective_yields[name].items():
            if mineral in mineral_totals:
                mineral_totals[mineral] += per_batch_qty * batches

    return PurchaseResult(
        purchase_list=purchase_list,
        total_volume_m3=total_volume,
        mineral_totals=mineral_totals,
    )
