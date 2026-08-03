from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.optimizer import InfeasibleError, PurchaseResult, solve_purchase_list
from app.reprocessing import ReprocessingInputs
from app.sde import OreData, get_connection, load_compressed_ore_data

_cache: dict[str, OreData] = {}


def _refresh_cache() -> None:
    conn = get_connection()
    try:
        _cache.clear()
        _cache.update(load_compressed_ore_data(conn))
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _refresh_cache()
    yield


app = FastAPI(title="Compressed Ore Purchase-List Optimizer", lifespan=lifespan)


class PurchaseListRequest(BaseModel):
    required_minerals: dict[str, float]
    allowed_ores: list[str] | None = None
    overage: dict[str, float] | None = None
    reprocessing: ReprocessingInputs


class PurchaseLineResponse(BaseModel):
    ore: str
    quantity: int
    volume_m3: float


class PurchaseListResponse(BaseModel):
    purchase_list: list[PurchaseLineResponse]
    total_volume_m3: float
    mineral_totals: dict[str, float]


class OreSummary(BaseModel):
    name: str
    volume_m3: float
    portion_size: int
    skill_type_id: int | None
    base_yields: dict[str, int]


@app.post("/purchase-list", response_model=PurchaseListResponse)
def purchase_list(request: PurchaseListRequest) -> PurchaseListResponse:
    try:
        result: PurchaseResult = solve_purchase_list(
            ores=_cache,
            required_minerals=request.required_minerals,
            allowed_ores=request.allowed_ores,
            overage=request.overage,
            reprocessing=request.reprocessing,
        )
    except InfeasibleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return PurchaseListResponse(
        purchase_list=[
            PurchaseLineResponse(ore=line.ore, quantity=line.quantity, volume_m3=line.volume_m3)
            for line in result.purchase_list
        ],
        total_volume_m3=result.total_volume_m3,
        mineral_totals=result.mineral_totals,
    )


@app.post("/refresh")
def refresh() -> dict[str, int]:
    _refresh_cache()
    return {"ore_count": len(_cache)}


@app.get("/ores", response_model=list[OreSummary])
def list_ores() -> list[OreSummary]:
    return [
        OreSummary(
            name=ore.name,
            volume_m3=ore.volume_m3,
            portion_size=ore.portion_size,
            skill_type_id=ore.skill_type_id,
            base_yields=ore.base_yields,
        )
        for ore in _cache.values()
    ]
