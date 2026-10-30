from decimal import Decimal

from app import sde
from app.sde import load_compressed_ore_data


class FakeCursor:
    def __init__(self, metadata, yields):
        self.results = {sde._ORE_METADATA_QUERY: metadata, sde._ORE_YIELDS_QUERY: yields}
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self.rows = self.results[sql]

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, metadata=(), yields=()):
        self.fake_cursor = FakeCursor(metadata, yields)

    def cursor(self):
        return self.fake_cursor


def metadata(type_id, volume=0.1, portion=100, skill=60377.0):
    return {"type_id": type_id, "volume_m3": volume, "portion_size": portion, "skill_type_id": skill}


def yield_row(type_id, mineral, quantity):
    return {"type_id": type_id, "mineral_type_id": mineral, "quantity": quantity}


def test_builds_ores_with_their_yields():
    conn = FakeConnection(
        [metadata(1, volume=Decimal("0.15"), portion=100), metadata(2, volume=1000.0, portion=1)],
        [yield_row(1, 34, 400), yield_row(1, 35, 200), yield_row(2, 16272, 10)],
    )
    ores = load_compressed_ore_data(conn)
    assert set(ores) == {1, 2}
    assert ores[1].volume_m3 == 0.15
    assert isinstance(ores[1].volume_m3, float)
    assert ores[1].portion_size == 100
    assert ores[1].base_yields == {34: 400, 35: 200}
    assert ores[2].portion_size == 1
    assert ores[2].base_yields == {16272: 10}


def test_skill_stored_as_a_float_comes_back_as_an_int():
    ores = load_compressed_ore_data(FakeConnection([metadata(1, skill=60377.0)]))
    assert ores[1].skill_type_id == 60377
    assert type(ores[1].skill_type_id) is int


def test_ore_with_no_skill_attribute_keeps_none():
    ores = load_compressed_ore_data(FakeConnection([metadata(1, skill=None)]))
    assert ores[1].skill_type_id is None


def test_yields_for_unknown_ores_are_ignored():
    ores = load_compressed_ore_data(FakeConnection([metadata(1)], [yield_row(99, 34, 1)]))
    assert set(ores) == {1}
    assert ores[1].base_yields == {}


def test_queries_the_reprocessing_skill_attribute():
    conn = FakeConnection()
    load_compressed_ore_data(conn)
    assert conn.fake_cursor.executed[0] == (sde._ORE_METADATA_QUERY, (790,))
