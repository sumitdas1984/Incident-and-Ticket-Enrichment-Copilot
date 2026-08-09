# Coverage baseline

Feature 8.1 (Story 8.1.1 — "Coverage ≥ 80 % on the core packages")
introduces an explicit coverage signal so a future drop is easy
to spot. The numbers below are the **baseline** — the coverage
report the CI runner generates on every push against this
baseline, and a regression below the thresholds below is the
signal something needs attention.

## Thresholds

| Package | Min | Notes |
|---|---|---|
| `core/` | 95 % | Configuration, domain, exceptions, logging — the foundation. |
| `rag/` (excluding `__main__.py`) | 80 % | Ingestion pipeline + retrieval service. |
| `apps/backend/` (excluding `__main__.py`) | 70 % | Orchestrator + routes. |
| `apps/frontend/` (excluding `__main__.py`) | 80 % | GUI clients + UI render. |
| `connectors/` (excluding `__main__.py`) | 80 % | Alarm-api + ticket-mock. |
| `mcp-servers/` | 80 % | Both MCP servers + their tools. |

`__main__.py` modules are excluded — they exist to be run as
console scripts and are not exercised by unit tests in normal
runs.

## How coverage is generated

```bash
uv run pytest -ra -m "not slow_embeddings" \
  --cov=apps --cov=rag --cov=connectors \
  --cov=mcp_servers --cov=core
```

The CI runner (`.github/workflows/ci.yml`) runs the same command
on every push and uploads the `.coverage` file as an artifact
(7-day retention). The committed baseline below is a snapshot
from the most recent successful CI run on `developer`.

## Baseline (developer, 2026-08-08)

```
TOTAL                                                   3322    420    87%
```

### Per-package snapshot (last successful run)

```
Name                                  Stmts   Miss  Cover
-------------------------------------------------------------
apps/backend/__init__.py                  19      0   100%
apps/backend/orchestrator/__init__.py     13      0   100%
apps/backend/orchestrator/answer.py       43      3    93%
apps/backend/orchestrator/chain.py       114      7    94%
apps/backend/orchestrator/citations.py     6      0   100%
apps/backend/orchestrator/conversation.py 40      2    95%
apps/backend/orchestrator/errors.py        5      0   100%
apps/backend/orchestrator/incident.py     89      5    94%
apps/backend/orchestrator/llm_client.py   76     37    51%
apps/backend/orchestrator/mcp_client.py   59     19    68%
apps/backend/orchestrator/plan.py         57      0   100%
apps/backend/orchestrator/planner.py     116      4    97%
apps/backend/orchestrator/rag_step.py      8      0   100%
apps/backend/orchestrator/request.py      57      0   100%
apps/backend/routes.py                    81     21    74%
apps/backend/wiring.py                    50      3    94%
apps/frontend/__init__.py                  1      0   100%
apps/frontend/chat_client.py              94     10    89%
apps/frontend/ticket_client.py           121     17    86%
apps/frontend/ui.py                      382     77    80%
connectors/alarm_api/__init__.py           2      0   100%
connectors/alarm_api/app.py               22      0   100%
connectors/alarm_api/auth.py               9      0   100%
connectors/alarm_api/errors.py            41      2    95%
connectors/alarm_api/models.py           140      0   100%
connectors/alarm_api/routers/alarms.py    59      0   100%
connectors/alarm_api/routers/analytics.py   9      0   100%
connectors/alarm_api/routers/assets.py     18      0   100%
connectors/alarm_api/routers/calculations.py 19   0   100%
connectors/alarm_api/routers/health.py      7      0   100%
connectors/alarm_api/routers/recommendations.py 15 2    87%
connectors/alarm_api/routers/tickets.py    18      0   100%
connectors/alarm_api/seed.py               7      0   100%
connectors/alarm_api/store.py            163     28    83%
connectors/ticket_mock/__init__.py         4      0   100%
connectors/ticket_mock/app.py             15      0   100%
connectors/ticket_mock/auth.py             9      0   100%
connectors/ticket_mock/draft.py           29      0   100%
connectors/ticket_mock/models.py          66      0   100%
connectors/ticket_mock/routers/health.py   7      1    86%
connectors/ticket_mock/routers/tickets.py 49      9    82%
connectors/ticket_mock/search.py          31      3    90%
connectors/ticket_mock/store.py           39      0   100%
core/__init__.py                          2      0   100%
core/config.py                           37      0   100%
core/domain.py                           72      0   100%
core/exceptions.py                        8      0   100%
core/logging.py                          26      1    96%
core/utils.py                            25      0   100%
mcp-servers/alarm-management/__init__.py   6      0   100%
mcp-servers/alarm-management/alarm_api_client.py 79  7  91%
mcp-servers/alarm-management/health.py    25      2    92%
mcp-servers/alarm-management/lifespan.py  24      2    92%
mcp-servers/alarm-management/registry.py  82     15    82%
mcp-servers/alarm-management/retry.py     54      1    98%
mcp-servers/alarm-management/tools.py     56      7    88%
mcp-servers/ticketing/__init__.py         0      0   100%
mcp-servers/ticketing/ticket_client.py    35      5    86%
mcp-servers/ticketing/tools.py            30      4    87%
rag/ingestion/__init__.py                 8      0   100%
rag/ingestion/chunker.py                 75      1    99%
rag/ingestion/embedder.py                55     17    69%
rag/ingestion/errors.py                   2      0   100%
rag/ingestion/index.py                   45      0   100%
rag/ingestion/loader.py                  68      2    97%
rag/ingestion/pipeline.py                44      5    89%
rag/retrieval/__init__.py                 6      0   100%
rag/retrieval/citations.py               32      0   100%
rag/retrieval/injection.py               25      0   100%
rag/retrieval/ranking.py                 27      0   100%
rag/retrieval/service.py                 72      2    97%
```

## Known gaps (deliberate)

| File | Coverage | Why below 100 % |
|---|---|---|
| `apps/backend/orchestrator/llm_client.py` | 51 % | The OpenAI / Anthropic SDK wrappers are unreachable in CI without API keys; tested via mocks in `tests/unit/orchestrator/test_llm_client.py` but `MockLLMClient` is the production path so the live SDK lines are not hit. |
| `apps/backend/orchestrator/mcp_client.py` | 68 % | Async transport errors (timeout, connection refused) aren't exercised in unit tests — those paths live in `tests/integration/`. |
| `apps/backend/routes.py` | 74 % | The `try/except` error-envelope branches for `MCPError` / `RAGError` / `CopilotError` aren't covered; the happy path is. |
| `rag/ingestion/embedder.py` | 69 % | The `SentenceTransformerEmbeddingModel` class downloads weights from Hugging Face on first run; gated behind `@pytest.mark.slow_embeddings` (excluded from CI). |

These are intentional — the live paths either need network /
credentials we don't ship to CI, or are exercised by integration
tests not counted in the unit-coverage report.