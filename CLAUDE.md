# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local-only FastAPI service that computes the minimal-volume set of EVE Online compressed ores to buy in order to cover a required list of minerals (reprocessing output), given constraints on which ores are allowed and how much overage per mineral is acceptable. It's consumed by a separate PHP website over HTTP; this service has no auth (assumes localhost-only access) and no persistent database of its own — it's a stateless computation layer in front of the player's live EVE SDE MySQL database.

## Commands

- Install/sync deps: `uv sync`
- Run the server: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` (add `--reload` for dev)
- Run any one-off script/REPL against the app code: `uv run python3 -c "..."`
- No test suite exists yet. There is no lint/format config configured either.

Requires a running MySQL instance with the EVE Static Data Export loaded (Fuzzwork-style schema), reachable via the credentials in `.env` (see `.env.example` for the shape — copy it to `.env` and fill in real values; `.env` is gitignored and must never be committed).

## Architecture

The whole app is four small modules under `app/`, each with one job, wired together in `app/main.py`:

- **`app/sde.py`** — the only place that talks to MySQL. `load_compressed_ore_data()` returns `dict[ore_name -> OreData]` by joining three tables:
  - `compressibleTypes(typeID, compressedTypeID)` is the authoritative list of which typeIDs are compressed ore — there is no group/category-based way to identify them.
  - `invTypeMaterials.quantity` gives reprocessing yield, but **it's the yield for one full 100-unit batch at 100% base yield, not a per-unit value** — this is the single most important non-obvious fact in the codebase and everything downstream depends on getting it right.
  - The ore's required reprocessing skill is looked up via `dgmTypeAttributes` (attributeID `790`, `reprocessingSkillType`) on the **raw** ore's typeID (compressed types have this attribute NULL), with the skill typeID stored in `valueFloat` rather than `valueInt`.
  - This data is loaded once at FastAPI startup (`lifespan` in `main.py`) and cached in memory in the module-level `_cache` dict; `POST /refresh` reloads it without restarting the process. There is no periodic polling.

- **`app/reprocessing.py`** — pure functions/Pydantic models implementing the yield formula from https://wiki.eveuniversity.org/Reprocessing. `ore_yield_multiplier()` takes a skill typeID and a `ReprocessingInputs` request object and returns a 0-1 fraction, branching on NPC station (base yield + standings tax) vs. Upwell structure (rig tier / security bonus / structure type bonus, no standings tax). These inputs are supplied per-request by the caller — they describe the *player's* skills and location, not anything about the SDE, so they are never cached.

- **`app/optimizer.py`** — builds and solves the integer program with PuLP/CBC. The decision variable is number of **100-unit batches** per ore (not raw unit count), because `invTypeMaterials.quantity` is already a per-batch figure — multiplying by units instead of batches is the classic bug to watch for here. Objective minimizes total m³ (`ore.volume_m3 * 100 * batches`, since volume genuinely is per-unit); mineral constraints use `effective_yield * batches` (no `* 100`). Raises `InfeasibleError` when CBC can't find a feasible solution (e.g. a required mineral isn't producible by any allowed ore, or an overage cap is too tight for the 100-unit batch granularity).

- **`app/main.py`** — FastAPI routes and Pydantic request/response schemas: `POST /purchase-list` (the main endpoint), `POST /refresh`, `GET /ores` (lets the PHP site build an ore-picker UI and see required skill IDs).

### Request contract gotchas

- `allowed_ores` is a list of ore *names* (as returned by `GET /ores`), not typeIDs.
- `ore_processing_skills` in `ReprocessingInputs` is keyed by **skill typeID** (e.g. `60377` = "Simple Ore Processing"), not by ore name or group — this was an explicit design choice since the skill-to-ore mapping is many-to-one (about a dozen skills cover all ore groups) and only discoverable via the `dgmTypeAttributes` join, not a naming convention.
- `overage` and `allowed_ores` are both optional; omitting `overage` for a mineral means unbounded overage is acceptable for it.
