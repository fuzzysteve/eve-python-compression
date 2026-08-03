# EVE Compressed Ore Purchase-List Optimizer

A local-only FastAPI service that computes the minimal-volume set of compressed ores to buy in order to cover a required list of minerals, given optional restrictions on which ores may be used and how much overage per mineral is acceptable. It solves an integer program (via PuLP/CBC) using live reprocessing yield data pulled from an EVE Online Static Data Export (SDE) MySQL database.

Intended to be called over HTTP by another application (e.g. a PHP website) running on the same machine — there is no authentication.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A MySQL database loaded with the EVE SDE (Fuzzwork-style schema), including a `compressibleTypes` table

## Setup

```bash
uv sync
cp .env.example .env
```

Edit `.env` with your database connection details:

```
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=eve
```

## Running

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Running as a systemd service (autostart)

An `eve-compression.service` unit file is included. It assumes `uv` is installed at `/root/.local/bin/uv` and depends on `mariadb.service` — adjust both if your setup differs.

```bash
cp eve-compression.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now eve-compression.service
```

Check status/logs with `systemctl status eve-compression.service` / `journalctl -u eve-compression.service -f`.

Add `--reload` during development to auto-restart on code changes. Ore/mineral data is loaded from the database once at startup; call `POST /refresh` afterward to reload without restarting the process (e.g. after an SDE update).

## API

### `POST /purchase-list`

Computes the purchase list. Ore quantities are always whole multiples of 100 (EVE's reprocessing batch size).

Request body:

```json
{
  "required_minerals": { "Tritanium": 1000000, "Pyerite": 500000, "Mexallon": 100000 },
  "allowed_ores": ["Compressed Veldspar", "Compressed Scordite"],
  "overage": { "Tritanium": 0.05 },
  "reprocessing": {
    "reprocessing_skill": 5,
    "reprocessing_efficiency_skill": 5,
    "ore_processing_skills": { "60377": 5, "60378": 4 },
    "implant_bonus": 0.0,
    "location": {
      "type": "npc_station",
      "base_yield": 0.5,
      "standing": 6.67
    }
  }
}
```

- `required_minerals` — minimum quantity of each mineral needed. Required.
- `allowed_ores` — restrict which compressed ores may be purchased, by name (see `GET /ores`). Omit to allow all ores.
- `overage` — per-mineral cap on acceptable excess, as a fraction (`0.05` = up to 5% over the minimum). Minerals not listed here have no upper bound.
- `reprocessing` — describes the player's skills and reprocessing location, used to compute actual yield. Required.
  - `ore_processing_skills` is keyed by **skill typeID** (see `GET /ores` for which skill each ore requires), not ore or group name.
  - `location.type` is either `"npc_station"` (fields: `base_yield`, `standing`) or `"structure"` (fields: `structure_bonus` — `standard`/`athanor`/`tatara`, `rig_tier` — `0`/`1`/`3`, `security` — `high_sec`/`low_sec`/`null_sec`).

Response body:

```json
{
  "purchase_list": [
    { "ore": "Compressed Veldspar", "quantity": 36000, "volume_m3": 36.0 }
  ],
  "total_volume_m3": 36.0,
  "mineral_totals": { "Tritanium": 100188.0 }
}
```

Returns `422` with a descriptive message if no combination of the allowed ores can satisfy the requirements (e.g. an unproducible mineral, or an overage cap too tight for the batch size).

### `GET /ores`

Lists all cached compressed ore types: name, volume per unit, batch (portion) size, required reprocessing skill typeID, and base (unscaled) mineral yields per batch. Useful for building an ore picker UI and discovering skill typeIDs.

### `POST /refresh`

Reloads ore/mineral data from the database. Returns `{"ore_count": <n>}`.

## Example

```bash
curl -X POST localhost:8000/purchase-list \
  -H "Content-Type: application/json" \
  -d '{
    "required_minerals": {"Tritanium": 100000},
    "allowed_ores": ["Compressed Veldspar"],
    "reprocessing": {
      "reprocessing_skill": 5,
      "reprocessing_efficiency_skill": 5,
      "ore_processing_skills": {"60377": 5},
      "location": {"type": "npc_station", "base_yield": 0.5, "standing": 6.67}
    }
  }'
```
