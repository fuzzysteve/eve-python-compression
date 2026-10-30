"""Shared fixtures. No MySQL connection is ever made: the ore data is synthetic and
CBC (which is real, and fast on problems this size) is the only external piece.

app.config reads these at import and load_dotenv() only fills in vars that are unset,
so setting every one here keeps the real .env out of the tests.
"""

import os

os.environ.update(
    DB_HOST="db.invalid",
    DB_PORT="3306",
    DB_USER="test",
    DB_PASSWORD="test",
    DB_NAME="test",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.reprocessing import ReprocessingInputs  # noqa: E402
from app.sde import OreData  # noqa: E402

TRITANIUM = 34
PYERITE = 35
MEXALLON = 36
HEAVY_WATER = 16272

SKILL_A = 60377
SKILL_B = 60378


def ore(type_id, volume=0.1, portion=100, skill=SKILL_A, **yields):
    """OreData with yields given as m<mineral typeID>=quantity."""
    return OreData(
        type_id=type_id,
        volume_m3=volume,
        portion_size=portion,
        skill_type_id=skill,
        base_yields={int(k[1:]): v for k, v in yields.items()},
    )


def inputs(base_yield=1.0, **kwargs):
    """Station at full standing: with no skills, the multiplier is exactly base_yield."""
    return ReprocessingInputs(
        location={"type": "npc_station", "base_yield": base_yield, "standing": 6.67}, **kwargs
    )


@pytest.fixture
def ores():
    """Installed as the app's cache for the duration of the test."""
    data = {
        1001: ore(1001, volume=0.1, m34=400, m35=200),
        1002: ore(1002, volume=0.2, m34=1000),
        1003: ore(1003, volume=0.1, m36=50),
        2001: ore(2001, volume=10.0, portion=1, skill=SKILL_B, m16272=10),
    }
    main._cache.clear()
    main._cache.update(data)
    yield data
    main._cache.clear()


@pytest.fixture
def client(ores):
    # Not a context manager: that would run lifespan, which connects to MySQL.
    return TestClient(main.app)
