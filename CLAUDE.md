# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local-only FastAPI service that computes the minimal-volume set of EVE Online compressed ores to buy in order to cover a required list of minerals (reprocessing output), given constraints on which ores are allowed and how much overage per mineral is acceptable. It's consumed by a separate PHP website over HTTP; this service has no auth (assumes localhost-only access) and no persistent database of its own — it's a stateless computation layer in front of the player's live EVE SDE MySQL database.

## Commands

- Install/sync deps: `uv sync`
- Run the server: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` (add `--reload` for dev)
- Run any one-off script/REPL against the app code: `uv run python3 -c "..."`
- No test suite exists yet. There is no lint/format config configured either.
- Outdated-dependency checks are not run from this repo: the Discord bot's daily `fuzzworkbot-update-check` (`/home/discordbot/src/fuzzworkbot/update_check.py`) checks this project's `.venv` too and posts to Discord. To upgrade: `uv lock --upgrade && uv sync && systemctl restart eve-compression`.
- **Keep cbcbox (the CBC binary) on the version `pulp[cbc]` allows (`<2.931`, currently 2.929) — don't override it.** cbcbox 2.931+ builds CBC's newer "next" branch. Tested 2026-10-28 by running 52 real `/purchase-list` requests against 2.929 vs 2.935: 2.935 wrongly reported a feasible request as infeasible ("No combination of the allowed ores…", reproducible every time; 2.929 solves it in 0.01s and its answer satisfies every constraint), and without a time limit one request hung CBC for 5+ minutes (2.929: 88s). The daily update check will keep listing cbcbox as outdated; that's expected. Before ever lifting the pin, rerun a real-request comparison like that one and check every 422 as well as every 200.

Requires a running MySQL instance with the EVE Static Data Export loaded (Fuzzwork-style schema), reachable via the credentials in `.env` (see `.env.example` for the shape — copy it to `.env` and fill in real values; `.env` is gitignored and must never be committed).

## Architecture

The whole app is four small modules under `app/`, each with one job, wired together in `app/main.py`:

- **`app/sde.py`** — the only place that talks to MySQL. `load_compressed_ore_data()` returns `dict[ore_type_id -> OreData]` by joining three tables. **The whole app is ID-only end to end — no ore/mineral/skill names ever appear in the data model or the API contract**, only EVE typeIDs (ore typeID, mineral typeID, skill typeID). Callers are expected to already have their own typeID -> name mapping (e.g. from their own copy of `invTypes`) if they need to display names.
  - `compressibleTypes(typeID, compressedTypeID)` is the authoritative list of which typeIDs are compressed ore — there is no group/category-based way to identify them.
  - `invTypeMaterials.quantity` gives reprocessing yield, keyed by `materialTypeID`, but **it's the yield for one full `portionSize` batch at 100% base yield, not a per-unit value** — this is the single most important non-obvious fact in the codebase and everything downstream depends on getting it right. `portionSize` is **not** a universal 100: it's 100 for ordinary ore, but **1 for ice and gas ("Harvestable Cloud")** — confirmed by querying every compressed type's `portionSize` directly, never assume it.
  - The ore's required reprocessing skill is looked up via `dgmTypeAttributes` (attributeID `790`, `reprocessingSkillType`) on the **raw** ore's typeID (compressed types have this attribute NULL), with the skill typeID stored in `valueFloat` rather than `valueInt`.
  - This data is loaded once at FastAPI startup (`lifespan` in `main.py`) and cached in memory in the module-level `_cache` dict; `POST /refresh` reloads it without restarting the process. There is no periodic polling.

- **`app/reprocessing.py`** — pure functions/Pydantic models implementing the yield formula from https://wiki.eveuniversity.org/Reprocessing. `ore_yield_multiplier()` takes a skill typeID and a `ReprocessingInputs` request object and returns a 0-1 fraction, branching on NPC station (base yield + standings tax) vs. Upwell structure (rig tier / security bonus / structure type bonus, no standings tax). These inputs are supplied per-request by the caller — they describe the *player's* skills and location, not anything about the SDE, so they are never cached.

- **`app/optimizer.py`** — builds and solves the integer program with PuLP/CBC. The decision variable is number of **`portion_size`-unit batches** per ore (not raw unit count, and not hardcoded to 100 — read `ore.portion_size` per ore, since ice/gas are 1), because `invTypeMaterials.quantity` is already a per-batch figure — multiplying by units instead of batches is the classic bug to watch for here. Objective minimizes total m³ (`ore.volume_m3 * ore.portion_size * batches`, since volume genuinely is per-unit); mineral constraints use `effective_yield * batches` (no extra multiplier). The LP itself works with continuous (unrounded) yield values internally — that's fine because `floor(x) >= n` iff `x >= n` for integer `n`, so a continuous solution meeting the requirement also meets it after truncation. `mineral_totals` in the result is floored (with a tiny epsilon to absorb float error) before being returned, since EVE always truncates reprocessing output to whole minerals — never report a fractional mineral quantity. Raises `InfeasibleError` when CBC can't find a feasible solution (e.g. a required mineral isn't producible by any allowed ore, or an overage cap is too tight for the batch granularity). Each solve has a hard wall-clock limit, `SOLVE_TIME_LIMIT_SECONDS` (10s): if CBC hits it (`LpSolveStatus.TimeLimit`), `TooComplexError` is raised and the request is rejected — even if CBC had a feasible best-so-far, since it may not be optimal. Both errors map to HTTP 422 with a `detail` message; check the message, not the status code, to tell "too complex" from "infeasible".

- **`app/main.py`** — FastAPI routes and Pydantic request/response schemas: `POST /purchase-list` (the main endpoint), `POST /refresh`, `GET /ores` (lets the PHP site build an ore-picker UI and see required skill IDs).

### Request contract gotchas

- Everything is keyed by typeID, never by name: `required_minerals`/`overage`/`mineral_totals` are keyed by **mineral typeID** (e.g. `34` = Tritanium), `allowed_ores`/`purchase_list[].ore_type_id` use **compressed ore typeID** (as returned by `GET /ores`), and `ore_processing_skills` is keyed by **skill typeID** (e.g. `60377` = "Simple Ore Processing"). None of these are ore/group names — the skill mapping in particular is many-to-one (about a dozen skills cover all ore groups) and only discoverable via the `dgmTypeAttributes` join, not a naming convention.
- JSON object keys are always strings on the wire (e.g. `{"34": 100000}`), but Pydantic coerces them to `int` for `dict[int, ...]` fields — don't add unnecessary `str()`/`int()` conversion shims for this, it's handled automatically.
- `overage` and `allowed_ores` are both optional; omitting `overage` for a mineral means unbounded overage is acceptable for it.
