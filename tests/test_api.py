import pytest
from fastapi.testclient import TestClient

from app import main
from tests.conftest import ore

STATION = {"location": {"type": "npc_station", "base_yield": 1.0, "standing": 6.67}}


def purchase(client, **body):
    return client.post("/purchase-list", json={"reprocessing": STATION, **body})


def test_purchase_list(client):
    response = purchase(client, required_minerals={"34": 1000}, allowed_ores=[1002])
    assert response.status_code == 200
    assert response.json() == {
        "purchase_list": [{"ore_type_id": 1002, "quantity": 100, "volume_m3": 20.0}],
        "total_volume_m3": 20.0,
        "mineral_totals": {"34": 1000},
    }


def test_purchase_list_considers_every_ore_when_allowed_ores_is_omitted(client):
    response = purchase(client, required_minerals={"34": 400, "36": 50})
    assert response.status_code == 200
    assert {line["ore_type_id"] for line in response.json()["purchase_list"]} == {1001, 1003}


def test_purchase_list_applies_reprocessing_inputs(client):
    reprocessing = {"location": {"type": "npc_station", "base_yield": 0.5, "standing": 6.67}}
    response = client.post(
        "/purchase-list",
        json={"required_minerals": {"34": 500}, "allowed_ores": [1002], "reprocessing": reprocessing},
    )
    assert response.json()["mineral_totals"] == {"34": 500}


def test_purchase_list_honours_overage(client):
    response = purchase(client, required_minerals={"34": 900}, allowed_ores=[1002], overage={"34": 0.05})
    assert response.status_code == 422
    assert "No combination" in response.json()["detail"]


def test_ice_quantities_are_not_scaled_to_100(client):
    response = purchase(client, required_minerals={"16272": 25})
    assert response.json()["purchase_list"] == [{"ore_type_id": 2001, "quantity": 3, "volume_m3": 30.0}]


def test_unknown_ore_is_a_422_with_a_reason(client):
    response = purchase(client, required_minerals={"34": 1}, allowed_ores=[9999])
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown ore type ID(s): 9999"


def test_too_complex_is_a_422_with_its_own_message(client, monkeypatch):
    from app.optimizer import TooComplexError

    def too_complex(**kwargs):
        raise TooComplexError("too complex")

    monkeypatch.setattr(main, "solve_purchase_list", too_complex)
    response = purchase(client, required_minerals={"34": 1})
    assert response.status_code == 422
    assert response.json()["detail"] == "too complex"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"required_minerals": {"34": 1}},
        {"required_minerals": "lots", "reprocessing": STATION},
        {"required_minerals": {"Tritanium": 1}, "reprocessing": STATION},
        {"required_minerals": {"34": 1}, "reprocessing": {"location": {"type": "moon"}}},
        {"required_minerals": {"34": 1}, "reprocessing": {"location": {"type": "structure", "rig_tier": 2}}},
    ],
)
def test_malformed_requests_are_rejected(client, body):
    assert client.post("/purchase-list", json=body).status_code == 422


def test_ores_lists_the_cache(client):
    response = client.get("/ores")
    assert response.status_code == 200
    by_id = {o["type_id"]: o for o in response.json()}
    assert set(by_id) == {1001, 1002, 1003, 2001}
    assert by_id[1001] == {
        "type_id": 1001,
        "volume_m3": 0.1,
        "portion_size": 100,
        "skill_type_id": 60377,
        "base_yields": {"34": 400, "35": 200},
    }
    assert by_id[2001]["portion_size"] == 1


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_refresh_replaces_the_cache_and_closes_the_connection(client, monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(main, "get_connection", lambda: conn)
    monkeypatch.setattr(main, "load_compressed_ore_data", lambda c: {5: ore(5, m34=1)})
    response = client.post("/refresh")
    assert response.json() == {"ore_count": 1}
    assert set(main._cache) == {5}
    assert conn.closed


def test_refresh_closes_the_connection_when_the_load_fails(ores, monkeypatch):
    conn = FakeConnection()

    def fail(c):
        raise RuntimeError("db went away")

    monkeypatch.setattr(main, "get_connection", lambda: conn)
    monkeypatch.setattr(main, "load_compressed_ore_data", fail)
    with pytest.raises(RuntimeError):
        main._refresh_cache()
    assert conn.closed


@pytest.mark.xfail(strict=True, reason="_refresh_cache clears the cache before loading, so a failed load empties it")
def test_failed_refresh_keeps_the_ores_already_loaded(ores, monkeypatch):
    def fail(c):
        raise RuntimeError("db went away")

    monkeypatch.setattr(main, "get_connection", FakeConnection)
    monkeypatch.setattr(main, "load_compressed_ore_data", fail)
    with pytest.raises(RuntimeError):
        main._refresh_cache()
    assert set(main._cache) == set(ores)


def test_startup_loads_the_cache(monkeypatch):
    monkeypatch.setattr(main, "get_connection", FakeConnection)
    monkeypatch.setattr(main, "load_compressed_ore_data", lambda c: {5: ore(5, m34=1)})
    main._cache.clear()
    with TestClient(main.app) as client:
        assert [o["type_id"] for o in client.get("/ores").json()] == [5]
    main._cache.clear()
