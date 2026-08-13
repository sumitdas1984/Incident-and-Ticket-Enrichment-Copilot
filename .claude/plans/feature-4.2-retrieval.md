# Plan — Feature 4.2: Retrieval (Stories 4.2.1 + 4.2.2)

> **Context.** Feature 4.1 ships the corpus and the ingestion pipeline. The persisted index is on disk (`var/index/v1.pkl`) and Story 4.2's retrieval service consumes it. Two stories: **4.2.1** semantic retrieval with citations, **4.2.2** low-confidence / no-result handling + prompt-injection defence. Both ship together — the safety layer is part of the retrieval contract, not a separate feature.
>
> **Parent Issues:** Epic 4: Knowledge Retrieval (RAG) — `#5`; Feature 4.2: Retrieval — `#19`; Story 4.2.1 — `#46`; Story 4.2.2 — `#47`.
>
> **What we don't do here**: ranking model fine-tuning, hybrid retrieval (BM25 + dense), re-ranking, online index updates. Out-of-scope items are forward-referenced in `docs/rag-design.md`.
>
> **What we explicitly do**: Hard constraint #6 from the brief — RAG must defend against prompt injection AND handle no-result / low-confidence cases explicitly. Both ship in this PR.

---

## 1. Goal

A retrieval service that:

1. Loads the persisted index from `var/index/v1.pkl` (or any path the caller specifies).
2. Embeds the user's query with the same embedding model that built the index.
3. Ranks chunks by cosine similarity, applies optional metadata filters, and returns the top-k.
4. Returns a structured `RetrievalResult` with `citations` (for the LLM prompt) and `confidence` (for the orchestrator's UX).
5. Drops any chunk whose content matches a configurable prompt-injection blocklist, logging every drop with `chunk_id` and the matched pattern.
6. Emits a clear "no confident answer" signal when the top score is below threshold or the result set is empty.

---

## 2. Approach

### 2.1 Module layout

```
rag/retrieval/
├── __init__.py          # public re-exports
├── service.py           # RetrievalService — the orchestrator-facing facade
├── citations.py         # Citation, RetrievalResult dataclasses
├── ranking.py           # cosine similarity, top-k, score normalisation
├── injection.py         # prompt-injection blocklist + dropper
└── (no __main__.py — retrieval is a library, not a CLI)
```

The `EmbeddingModel` and `InMemoryVectorIndex` from `rag.ingestion` are the inputs; the service is the only public surface.

### 2.2 Story 4.2.1 — Retrieval service + citations

#### 2.2.1 `rag/retrieval/citations.py`

```python
@dataclass(frozen=True)
class Citation:
    """One chunk's citation metadata. Rendered into the LLM prompt and the GUI."""
    doc_id: str
    chunk_id: str        # f"{doc_id}#{chunk_index}"
    title: str
    section: str | None  # nearest preceding Markdown header
    source_type: str
    asset_class: str | None
    severity: str | None
    excerpt: str         # first 200 chars of the chunk text
    score: float         # cosine similarity in [-1, 1] (typically [0, 1] for our embedder)

@dataclass(frozen=True)
class RetrievalResult:
    """The output of one retrieval call.
    Empty list + low confidence is a valid result (the orchestrator must surface it)."""
    citations: list[Citation]
    confidence: str       # "high" | "medium" | "low" | "none"
    top_score: float
    threshold: float
    dropped_count: int    # chunks dropped by the injection blocklist
```

#### 2.2.2 `rag/retrieval/ranking.py`

Pure-Python cosine similarity. `numpy` is already a transitive dep of `sentence-transformers`, so we use it without adding a new top-level dependency. Pure-Python fallback is not warranted for the corpus size (332 chunks).

```python
def cosine_similarity(a: list[float], b: list[float]) -> float: ...
def top_k(query_vec: list[float], candidates: list[IndexedChunk], k: int) -> list[tuple[IndexedChunk, float]]:
    """Return up to k (chunk, score) pairs sorted by descending score."""
```

#### 2.2.3 `rag/retrieval/service.py`

```python
class RetrievalService:
    """Consume the persisted index and answer queries with citations."""

    def __init__(
        self,
        *,
        index: InMemoryVectorIndex,
        embedder: EmbeddingModel,
        confidence_threshold: float = 0.30,        # below this → "low"
        medium_threshold: float = 0.50,            # below this → "medium"
        injection_blocklist: list[re.Pattern] | None = None,
    ): ...

    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> RetrievalResult:
        """Embed the query, rank, filter, drop injections, return citations + confidence."""
```

`RetrievalFilters` is a small frozen dataclass with optional `source_type`, `asset_class`, `severity` fields. None of these are required for the first iteration; they exist so Story 4.2's caller can opt into them without breaking changes.

### 2.3 Story 4.2.2 — Low-confidence + injection defence

#### 2.3.1 `rag/retrieval/injection.py`

A configurable blocklist of regex patterns. The default blocklist catches the two seeds we committed in `boiler-tube-leak-troubleshooting.md` and `cooling-water-pump-failure-kb.md`:

```python
DEFAULT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore previous instructions", re.IGNORECASE),
    re.compile(r"override mode", re.IGNORECASE),
    re.compile(r"disregard all (?:prior|previous) instructions", re.IGNORECASE),
    re.compile(r"system:.*override", re.IGNORECASE),
)
```

The retrieval service applies the blocklist to every chunk's text **before** ranking. Matches are dropped with a `rag.injection_dropped` log carrying `chunk_id`, `doc_id`, and the matched pattern's regex string.

The blocklist is configurable so an operator can add new patterns without code changes. Stories 4.2.3 is acknowledged in the design doc as a future hardening pass (LLM-based detection, structural sanitisation).

#### 2.3.2 Confidence bands

| Top score | Confidence |
|---|---|
| `>= 0.50` | `high` |
| `0.30 - 0.50` | `medium` |
| `< 0.30` | `low` |
| no chunks returned | `none` |

The thresholds are configurable on the constructor. The default of `0.30` is chosen so the bundled test corpus (six synthetic docs, ~332 chunks) returns *something* reasonable for a query like "boiler tube leak" — easy to recalibrate if retrieval quality changes.

The `RetrievalResult.confidence` is the orchestrator's signal to either:
- Render the citations directly to the LLM (high/medium).
- Render the citations with a "low confidence" caveat (low).
- Render an explicit "no confident answer" message (none).

#### 2.3.3 Empty index / no chunks

If the index is empty, the retrieval returns `RetrievalResult(citations=[], confidence="none", top_score=0.0, threshold=…, dropped_count=0)`. The caller (orchestrator) is responsible for surfacing the empty result to the user.

### 2.4 Public surface

```python
from rag.retrieval import (
    Citation,
    RetrievalResult,
    RetrievalService,
    RetrievalFilters,
    DEFAULT_INJECTION_PATTERNS,
)
```

### 2.5 Tests

| File | Coverage |
|---|---|
| `tests/unit/rag/test_ranking.py` | cosine similarity correctness, top-k ordering, ties, k > n, k = 0 |
| `tests/unit/rag/test_citations.py` | Citation construction, excerpt truncation, frozenness |
| `tests/unit/rag/test_service.py` | end-to-end retrieval against a small in-memory index; k=5 returns top-5 sorted by score; filters narrow results |
| `tests/unit/rag/test_low_confidence.py` | threshold bands; high/medium/low/none; empty index; below-threshold score |
| `tests/unit/rag/test_injection_defence.py` | blocklist drops chunks; default patterns catch the two corpus seeds; configurable blocklist; drop is logged |
| `tests/unit/rag/test_orchestrator_rag.py` | end-to-end: load persisted index, query, render citations + confidence |
| `tests/unit/rag/test_retrieval_corpus.py` | retrieval against the committed corpus returns sensible citations for a hand-picked query |

All tests use `DeterministicEmbeddingModel` so the suite is fast and deterministic. The real `SentenceTransformerEmbeddingModel` is gated behind `pytest.mark.slow_embeddings` (one test).

### 2.6 Documentation

`docs/rag-design.md` gets a new section "Retrieval reference implementation" that documents:

- `RetrievalService.retrieve(...)` API + signature.
- `Citation` and `RetrievalResult` dataclasses.
- The confidence thresholds and how they're propagated.
- The injection blocklist contract.
- The empty-result / no-confident-answer UX.

### 2.7 Non-goals

- **No hybrid retrieval (BM25 + dense).** Forward-reference.
- **No re-ranking.** Forward-reference.
- **No LLM-based injection detection.** This is the regex blocklist; LLM-based detection is a future hardening pass.
- **No online / incremental index updates.** The retrieval reads the persisted index; the ingestion pipeline is the only writer.
- **No frontend changes.** The GUI surfaces the citations in Epic 7 (Story 7.2.2).
- **No orchestrator integration here.** The thin orchestrator glue lands in Epic 5 (Story 5.1.3); this PR only ships the library + library-level tests.

### 2.8 Dependencies

No new dependencies. `numpy` is already a transitive dep of `sentence-transformers` (added in Feature 4.1). `re` is stdlib.

---

## 3. Critical files

### New

- `rag/retrieval/service.py`
- `rag/retrieval/citations.py`
- `rag/retrieval/ranking.py`
- `rag/retrieval/injection.py`
- `tests/unit/rag/test_ranking.py`
- `tests/unit/rag/test_citations.py`
- `tests/unit/rag/test_service.py`
- `tests/unit/rag/test_low_confidence.py`
- `tests/unit/rag/test_injection_defence.py`
- `tests/unit/rag/test_orchestrator_rag.py`
- `tests/unit/rag/test_retrieval_corpus.py`

### Modified

- `rag/retrieval/__init__.py` — re-export the public surface.
- `docs/rag-design.md` — replace the forward-reference sections with the concrete implementation.

### Untouched

- `rag/ingestion/` — the retrieval service consumes the index; it does not modify the ingestion pipeline.
- `mcp-servers/`, `apps/`, `connectors/`, `core/` — the retrieval is a library; orchestrator integration is a separate story.

---

## 4. Verification

1. **Static gates (must pass before push):**
   ```bash
   uv lock && uv sync
   uv run ruff check .
   uv run mypy apps rag connectors core
   uv run pytest -ra
   ```
   Expect: ~217 (Feature 4.1 baseline) + ~30 new retrieval tests = ~247 tests green.

2. **Live retrieval smoke:**
   ```python
   from pathlib import Path
   from rag.ingestion import InMemoryVectorIndex, DeterministicEmbeddingModel
   from rag.retrieval import RetrievalService

   idx = InMemoryVectorIndex.load(Path("var/index/v1.pkl"))
   service = RetrievalService(index=idx, embedder=DeterministicEmbeddingModel(dimension=384))
   result = service.retrieve("boiler tube leak troubleshooting", k=5)
   for c in result.citations:
       print(f"{c.chunk_id}  score={c.score:.3f}  conf={result.confidence}  section={c.section!r}")
   ```
   Expect: 5 sorted citations, top score ≥ 0.30, no dropped chunks.

3. **Blocklist smoke:**
   ```python
   result = service.retrieve("boiler tube leak")  # the seed string is in the docs
   # The chunk that contains "Ignore previous instructions" must be dropped.
   assert result.dropped_count >= 1
   ```

4. **Determinism smoke (two retrievals against the same index):**
   ```python
   a = service.retrieve("boiler tube leak", k=5)
   b = service.retrieve("boiler tube leak", k=5)
   assert [c.chunk_id for c in a.citations] == [c.chunk_id for c in b.citations]
   ```

5. **Lint / type / docs:** clean (see step 1).

---

## 5. Rollback

Trivial. The retrieval service is a new library; removing it is a `git revert`. The persisted index from Feature 4.1 is unaffected.

---

## 6. Branch + PR

- Branch: `feature/feature-4.2-retrieval` (off `developer` at `bcc8b50`, post-Feature-4.1 merge).
- Single PR closes both `#46` (4.2.1) and `#47` (4.2.2) — per the user's "both in one PR" decision for the safety-inclusive scope.
- After merge: the orchestrator story (5.1.3) can branch off and call `RetrievalService.retrieve(...)` from the same code path as the existing alarm-management MCP tools.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.
