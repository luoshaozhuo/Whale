# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Whale Repository Guide

This file defines repository-wide guidance for Claude Code in the Whale project.
It is aligned with AGENTS.md (the Codex equivalent) and references the same shared policy documents.

---

## 1. Commands

### Setup

```bash
pip install -e ".[dev]"
```

### Lint & type-check

```bash
black --check src/ tools/
mypy src/ tools/
```

### Run tests

```bash
pytest                                  # all tests (default: unit + integration)
pytest -m unit                          # unit only
pytest -m integration                   # integration only
pytest -m e2e                           # end-to-end (needs Docker infra)
pytest -m load                          # load tests
pytest -k "test_name_keyword"           # filter by test name
pytest tests/unit/tools/source_lab/test_fleet_update_selection.py  # single file
pytest -x                               # stop on first failure
```

### Run a single test

```bash
pytest tests/unit/ingest/test_scheduler.py::TestSourceScheduler::test_reload_clears_previous_jobs
```

### Ingest runtime

```bash
# Set env vars from .env.ingest.local first, then:
PYTHONPATH=src python -m whale.ingest
```

### Init database with sample data

```bash
PYTHONPATH=src python -m whale.ingest.framework.persistence.init_db --sample-data --non-interactive
```

### Environment setup

```bash
# Copy env template and edit as needed
cp .env.ingest.example .env.ingest.local
# Then source before running ingest
set -a; source .env.ingest.local; set +a
```

### Local dev infrastructure (Docker)

```bash
# Start PostgreSQL + Redis + Kafka
docker compose -f docker-compose.ingest-dev.yaml up -d

# Stop
docker compose -f docker-compose.ingest-dev.yaml down

# Full dev loop: recreate infra → init DB with sample data → start ingest
bash scripts/run_ingest_dev.sh
```

---

## 2. Architecture

The project is an energy data unification platform (能源数据统一平台), built incrementally from Level 0 data flow upward.

### 2.1 High-level structure

```text
src/whale/                    # Core platform
  ingest/                     # Data acquisition runtime (main active module)
  processing/                 # Data cleaning & normalization
  aggregation/                # Periodic, realtime, and ADS aggregation
  shared/                     # Cross-cutting: persistence, enums, time utils
  storage/                    # Storage layer (placeholder)

tools/source_lab/      # OPC UA simulation dev tooling (separate from core)
tests/                        # unit/, integration/, e2e/, performance/{endurance,load,stress}/
config/                       # Config files (currently empty — config is env-var driven)
scripts/                      # Dev scripts (run_ingest_dev.sh)
```

### 2.2 Ingest module — ports-adapters architecture

The `ingest/` module follows a strict ports-adapters pattern:

- **`ports/`** — Abstract interfaces (Python Protocols):
  - `source/` — `SourceAcquisitionPort`, `SourceAcquisitionDefinitionPort`, `SourceAcquisitionPortRegistry`
  - `state/` — `SourceStateCachePort`, `SourceStateSnapshotReaderPort`
  - `message/` — `MessagePublisherPort`
  - `runtime/` — `SourceRuntimeConfigPort`
  - `diagnostics.py` — `RuntimeDiagnosticsPort`
- **`adapters/`** — Concrete implementations:
  - `source/` — `OpcUaSourceAcquisitionAdapter`, `StaticSourceAcquisitionPortRegistry`
  - `state/` — `SqliteSourceStateCache`, `RedisSourceStateCache`
  - `message/` — `RelationalOutboxMessagePublisher`, `RedisStreamsMessagePublisher`, `KafkaMessagePublisher`
  - `config/` — `SourceRuntimeConfigRepository`, `OpcUaSourceAcquisitionDefinitionRepository`
- **`usecases/`** — Use cases with composed role objects:
  - `ExecuteSourceAcquisitionUseCase` (ONCE/POLLING)
  - `SubscribeSourceStateUseCase` (SUBSCRIPTION)
  - `BuildRuntimePlanUseCase`
  - `EmitStateSnapshotUseCase`
  - `roles/` — Single-responsibility role classes composed by use cases
  - `dtos/` — Data transfer objects shared between use cases
- **`runtime/`** — `SourceScheduler` wraps APScheduler, dispatches ONCE/POLLING/SUBSCRIPTION jobs
- **`entities/`** — `NodeState`, `SourceHealthState`
- **`config.py`** — `EnvironmentConfig` built from env vars at import time; available as `CONFIG`

Dependency wiring happens in `__main__.py` — it reads `CONFIG`, selects the right adapter backends, and assembles the scheduler.

### 2.3 source_simulation tool — also ports-adapters

- **`domain.py`** — Frozen dataclasses: `SimulatedSource`, `SimulatedPoint`, `SourceConnection`, `UpdateConfig`, etc.
- **`ports.py`** — `SourceSimulator` and `SourceReader` protocols
- **`fleet.py`** — `SourceSimulatorFleet`: one process per simulated source, managed with `multiprocessing`
- **`adapters/registry.py`** — `build_simulator()`: resolves protocol string to adapter
- **`adapters/opcua/`** — OPC UA simulator server (asyncua-based) and reader

### 2.4 Backend selection

Three backend dimensions, each controlled by an env var:

| Dimension | Env var | Options |
| --- | --- | --- |
| Database | `WHALE_INGEST_DATABASE_BACKEND` | `sqlite` (default), `postgresql` |
| State cache | `WHALE_INGEST_STATE_CACHE_BACKEND` | `relational` (default), `redis` |
| Message | `WHALE_INGEST_MESSAGE_BACKEND` | `relational_outbox` (default), `redis_streams`, `kafka` |

Constraint: `relational` state cache requires `sqlite` database backend.

---

## 3. Working style

- Keep responses concise and decision-oriented.
- Prioritize conclusions, next steps, impact scope, and constraints.
- Do not dump large code blocks unless explicitly requested.

---

## 4. Engineering approach

- Prefer incremental delivery and the smallest useful change.
- Avoid over-design and avoid introducing abstractions before they are needed.
- Preserve existing behavior unless the task explicitly changes it.
- Refactor in stages after behavior is stable, not preemptively.
- Validate changes with relevant checks and tests.

---

## 5. Change boundaries

- Do not perform unrelated refactors.
- Do not modify files outside the current task without clear need.
- Avoid formatting churn unrelated to the requested change.
- Keep new implementations consistent with the existing repository structure.

---

## 6. Task routing

- For Python implementation and validation, use Agent tool with subagent_type="general-purpose" and provide the `.codex/policies/` documents as context.
- Non-Python tasks should not inherit Python-specific policy details.

---

## 7. Repository policy documents

For Python tasks, Claude Code must follow the documents under `.codex/policies/`:
- `engineering-general.md` — cross-cutting engineering constraints
- `python-style.md` — Python code style and structure
- `python-typing.md` — Python typing expectations
- `python-docstrings.md` — Python docstring expectations
- `testing-policy.md` — test layers, validation, and completion criteria

These are mandatory project constraints when the task scope matches.

---

## 8. Reporting requirements

After completing a task, report:

1. what guidance and policy documents were followed
2. what files or sections were changed
3. what checks and tests were run
4. what conclusions come from policy compliance work
5. what conclusions come from tool-based validation
6. any remaining risks, environment limits, or unresolved ambiguities

Do not report completion using only "done", "passed", or raw tool output.

---

## 9. Prohibited behavior

- Do not skip repository guidance and jump straight to editing.
- Do not treat tool defaults as the source of truth.
- Do not equate "checks passed" with "all repository requirements satisfied".
- Do not claim completion without validation.
- Do not expand a local task into a broad redesign without need.
