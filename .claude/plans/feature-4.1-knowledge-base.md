# Plan — Feature 4.1: Knowledge Base (Stories 4.1.1 + 4.1.2)

> **Context.** The copilot's grounded answer is half MCP (live alarm data) and half RAG (operating-procedure knowledge). Epic 4 — Knowledge Retrieval (RAG) — adds the second half. Feature 4.1 is the **Knowledge Base**: Story 4.1.1 ships a synthetic document corpus, Story 4.1.2 ships the ingestion pipeline (extract → chunk → embed → index) that turns the corpus into a retrievable index. Feature 4.2 (Retrieval) follows; it builds on the index built here.
>
> **Scope of this PR (decided up front).** Both stories ship together so the pipeline is end-to-end green at merge time. The corpus is a *prerequisite* of the pipeline and is small enough that splitting the PR would just create a half-built intermediate state.
>
> **What we don't do here**:
> - **No retrieval.** That's Story 4.2.1 (semantic retrieval + citations) and 4.2.2 (low-confidence / no-result handling). The ingestion output is persisted; the retrieval service reads it in the next feature.
> - **No real embeddings service.** A `SentenceTransformerEmbeddingModel` wraps a local model (default `all-MiniLM-L6-v2`, ~80 MB, runs on CPU); the model is documented in `docs/rag-design.md`. No external API call, no cloud credentials.
> - **No hybrid retrieval.** Pure dense vector retrieval. BM25 / hybrid is out of scope for the timebox; it can land in Feature 4.2 if retrieval quality demands it.

---

## 1. Goal

A self-contained RAG knowledge base that:

1. Lives under `rag/documents/` as committed, synthetic-but-realistic Markdown (Story 4.1.1).
2. Can be rebuilt from scratch by `make ingest` (Story 4.1.2).
3. Emits a vector index on disk (persisted; not committed) that Story 4.2's retrieval service consumes.
4. Carries enough chunk-level metadata (doc_id, source_type, asset_class, severity, chunk_index, section) to power retrieval filtering and citations downstream.
5. Defends against prompt-injection from retrieved documents — applied at retrieval time, but the ingestion pipeline never *removes* the warning surface (it normalises text but keeps the original; retrieval is responsible for sanitisation, which lives in Story 4.2).

---

## 2. Approach

### 2.1 Story 4.1.1 — Synthetic corpus under `rag/documents/`

Six documents, ≥ 4 types, varied metadata:

| File | Type | asset_class | severity | Notes |
|---|---|---|---|---|
| `boiler-tube-leak-troubleshooting.md` | troubleshooting | boiler | critical | High-pressure boiler tube leak diagnostic + escalation |
| `compressor-surge-recovery.md` | troubleshooting | compressor | high | Centrifugal-compressor surge recovery procedure |
| `distillation-column-startup-sop.md` | procedure | distillation_column | medium | Standard operating procedure for column startup |
| `cooling-water-pump-failure-kb.md` | knowledge_article | cooling_water | high | Knowledge-base article on CW pump failure modes |
| `incident-2025-03-14-resolver-notes.md` | resolution_note | boiler | high | Past incident resolution timeline (synthetic) |
| `high-severity-alarm-escalation.md` | escalation | site | critical | Escalation procedure for site-wide critical alarms |

Each has YAML front-matter (parsed by `python-frontmatter` or hand-rolled — see § 2.2.3) with at least:

```yaml
---
doc_id: boiler-tube-leak-troubleshooting
title: Boiler Tube Leak — Troubleshooting Guide
source_type: troubleshooting
asset_class: boiler
severity: critical
version: 1.0
last_updated: 2026-07-01
tags: [boiler, leak, tube, pressure]
---
```

Why front-matter: it doubles as human-readable metadata for review and as the structured input to ingestion, so we don't need a separate sidecar metadata file. Markdown body holds the content; the body deliberately includes "IGNORE PREVIOUS INSTRUCTIONS"-style strings in *two* documents so Story 4.2's prompt-injection defence has something to defend against.

### 2.2 Story 4.1.2 — Ingestion pipeline

Four-stage pipeline: **load → chunk → embed → persist**. Each stage is a pure function / class with a stable interface so tests can substitute fakes (e.g. deterministic embedding model).

#### 2.2.1 `rag/ingestion/loader.py` — Markdown + front-matter extraction

```python
def load_documents(corpus_dir: Path) -> list[LoadedDocument]:
    """Walk corpus_dir, parse *.md files into LoadedDocument."""

@dataclass(frozen=True)
class LoadedDocument:
    doc_id: str           # from front-matter, also used as filename stem
    title: str
    source_type: str
    asset_class: str | None
    severity: str | None
    tags: list[str]
    body: str             # Markdown content, front-matter stripped
    path: Path
    version: str
    last_updated: str
```

Strategy:
- Walk `corpus_dir` for `**/*.md`.
- Split front-matter (`---\n...\n---\n`) from body with a small regex or `python-frontmatter`. Hand-rolled regex keeps the dep surface small — front-matter is a well-defined grammar.
- Fail loudly on malformed front-matter (typos here are worse than typos in body).
- Reject docs with duplicate `doc_id` (catches copy-paste mistakes).

#### 2.2.2 `rag/ingestion/chunker.py` — Sliding window with metadata

```python
def chunk_document(
    doc: LoadedDocument,
    *,
    chunk_size: int = 800,    # characters
    overlap: int = 100,
) -> list[Chunk]:
    """Slide a window over the document body, retaining section context."""

@dataclass(frozen=True)
class Chunk:
    chunk_id: str        # f"{doc_id}#{chunk_index}"
    doc_id: str
    chunk_index: int
    text: str
    section: str | None  # nearest preceding Markdown header
    source_type: str
    asset_class: str | None
    severity: str | None
    tags: list[str]
```

Design:
- Chunk by **characters**, not tokens — character-based is simpler, deterministic, and works regardless of embedding model. Token boundaries get fuzzy otherwise.
- Keep `overlap=100` (12.5 % of `chunk_size=800`) — enough to preserve context across boundaries without doubling the index.
- Walk section headers (`#`, `##`, `###`); each chunk inherits the nearest preceding header as `section`.
- Reject chunks < 50 chars (filter out accidental whitespace splits); merge with the previous chunk.

Why this shape: it gives Story 4.2 the metadata it needs for citations (`{doc_id}#{chunk_index}` is the citeable unit) and for filtering (`asset_class`, `severity`, `source_type`).

#### 2.2.3 `rag/ingestion/embedder.py` — Embedding model wrapper

```python
class EmbeddingModel(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class SentenceTransformerEmbeddingModel:
    """Wraps sentence-transformers (default: all-MiniLM-L6-v2)."""

    def __init__(self, *, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu"): ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Two realisations:
- `SentenceTransformerEmbeddingModel` — production path. Adds `sentence-transformers>=3.0` and `torch` deps.
- `DeterministicEmbeddingModel` — test path. Hashes text to a 384-dim vector; same input → same vector, deterministic, no model load. Used by tests so the suite stays under 1 s.

Why a `Protocol` boundary: it lets us substitute a `HashEmbeddingModel` or `MockEmbeddingModel` for Story 4.2's retrieval tests without standing up a real model. The ingestion pipeline never knows which is wired in.

Why `all-MiniLM-L6-v2`: 384-dim, ~80 MB, fast on CPU, strong baseline on industrial-procedure text per the public MTEB benchmark. Documented in `docs/rag-design.md` so reviewers can swap it.

#### 2.2.4 `rag/ingestion/index.py` — Pluggable vector store

```python
class VectorIndex(Protocol):
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def __len__(self) -> int: ...
    def save(self, path: Path) -> None: ...
    @classmethod
    def load(cls, path: Path) -> "VectorIndex": ...

class InMemoryVectorIndex:
    """Default. Stores chunks + vectors in RAM; pickles to disk."""

class FaissVectorIndex:        # future
    """Optional FAISS-backed index. Not in this PR."""
```

Storage choice: `InMemoryVectorIndex` (default) pickles to `var/index/v1.pkl`. Rationale:
- **Pluggable boundary** via the `VectorIndex` protocol so Story 4.2 can write a FAISS-backed variant if retrieval latency demands it.
- **No new infra dep** — pickle is stdlib, no `chromadb` or `faiss-cpu` to wrestle with on different platforms.
- **Deterministic rebuild** — `make ingest` deletes `var/index/` and rebuilds; same corpus + same embedder → same index byte-for-byte (verified by a test).
- **Good enough for 6 documents** — retrieval over a few hundred chunks is microseconds; FAISS optimisation isn't needed until the corpus is 100× bigger.

The `var/` directory is gitignored (already in the project layout under "Persistence").

#### 2.2.5 `rag/ingestion/pipeline.py` — Orchestrator + `make ingest`

```python
def run_ingestion(
    *,
    corpus_dir: Path,
    index_path: Path,
    embedder: EmbeddingModel | None = None,
    chunk_size: int = 800,
    overlap: int = 100,
) -> IngestionReport:
    """load → chunk → embed → persist. Returns a report."""

@dataclass(frozen=True)
class IngestionReport:
    documents: int
    chunks: int
    duration_s: float
    index_path: Path
```

CLI entry: `python -m rag.ingestion --corpus rag/documents --index var/index/v1.pkl`. Wired into the existing `Makefile`:

```make
ingest:
	uv run python -m rag.ingestion --corpus rag/documents --index var/index/v1.pkl
```

Reports `documents=N chunks=M duration=Xs index=path` on stdout, mirroring the make target's existing shape.

### 2.3 Dependencies (`pyproject.toml`)

```toml
dependencies = [
    ...
    # Embedding model for RAG ingestion (Feature 4.1). Pinned to a
    # small, CPU-friendly model so the corpus can be ingested in a
    # clean container without GPU / cloud credentials.
    "sentence-transformers>=3.0",
    # ``torch`` is a transitive dep of sentence-transformers;
    # declaring it explicitly so the lock file pins a known-good
    # version per platform.
    "torch>=2.1",
]
```

`torch` is large but unavoidable on the sentence-transformers path. Documented in `docs/rag-design.md` so reviewers see the rationale.

### 2.4 Test surface

New tests in `rag/tests/`:

| File | Coverage |
|---|---|
| `test_loader.py` | front-matter parse, body strip, duplicate `doc_id` rejection, missing-file path |
| `test_chunker.py` | chunk size bounds, overlap correctness, section assignment, short-chunk merge, index monotonicity |
| `test_embedder.py` | `DeterministicEmbeddingModel` shape + determinism, `SentenceTransformerEmbeddingModel` shape (only when model is loadable) |
| `test_index.py` | add → save → load round-trip, `__len__`, empty-index behaviour |
| `test_pipeline.py` | full end-to-end against `rag/documents/`, deterministic rebuild, report shape, index size matches `chunks` |
| `test_corpus.py` | every committed doc has required front-matter fields, ≥ 6 docs, ≥ 4 source types, no restricted-content markers |

Test-time embedder: `DeterministicEmbeddingModel` (always). The real `SentenceTransformerEmbeddingModel` is exercised in a single optional test (`@pytest.mark.slow_embeddings`) that's skipped in CI to avoid downloading model weights during PR checks. Documented in `docs/rag-design.md`.

### 2.5 Documentation

- `docs/rag-design.md` (NEW) — required by the brief. Covers: source types, ingestion, extraction, chunking + metadata, embedding model choice (with rationale), index store, citation construction, low-confidence handling (forward-reference to 4.2), prompt-injection defences (forward-reference to 4.2), index refresh.
- `docs/architecture.md` — not yet written; that's Story 9.1.2. Skip here; we'll point at it once it lands.
- `docs/mcp-tool-catalog.md` — unchanged (RAG isn't an MCP tool in this design).

---

## 3. Non-goals

- **No retrieval service** — Story 4.2.1. This PR stops at "the index is on disk, reloadable, queryable by a future retrieval service."
- **No reranking** — defer until retrieval quality is measurable.
- **No hybrid retrieval (BM25 + dense)** — pure dense retrieval in this PR. Forward-reference in `docs/rag-design.md`.
- **No incremental ingestion** — `make ingest` is a full rebuild. Incremental ingestion lands if / when the corpus crosses ~100 docs.
- **No front-matter library** — hand-rolled regex keeps the dep surface small. Front-matter is a well-defined grammar and the validator is 30 lines.
- **No GUI changes** — RAG surfaces in the GUI in Epic 7; not relevant here.

---

## 4. Critical files

### New

- `rag/documents/*.md` (6 files, Story 4.1.1)
- `rag/ingestion/loader.py`
- `rag/ingestion/chunker.py`
- `rag/ingestion/embedder.py`
- `rag/ingestion/index.py`
- `rag/ingestion/pipeline.py`
- `rag/ingestion/__main__.py` — CLI entry wired into `make ingest`
- `rag/tests/test_loader.py`
- `rag/tests/test_chunker.py`
- `rag/tests/test_embedder.py`
- `rag/tests/test_index.py`
- `rag/tests/test_pipeline.py`
- `rag/tests/test_corpus.py`
- `docs/rag-design.md`

### Modified

- `pyproject.toml` — add `sentence-transformers>=3.0`, `torch>=2.1`
- `Makefile` — wire `ingest:` target to `python -m rag.ingestion`
- `.gitignore` — add `var/` if not already there (it likely is, from Epic 1)
- `uv.lock` — regenerated by `uv lock`

### Untouched

- `mcp-servers/`, `apps/`, `connectors/`, `core/` — none of this affects existing code paths.

---

## 5. Verification

1. **Static checks (must pass before push):**
   ```bash
   uv lock
   uv sync
   uv run ruff check .
   uv run mypy apps rag connectors core
   uv run pytest -ra
   ```
   Expect: ~160 prior tests + ~25 new RAG tests = ~185 tests green.

2. **End-to-end smoke:**
   ```bash
   make ingest
   ```
   Expect:
   ```
   documents=6 chunks=NN duration=Xs index=var/index/v1.pkl
   ```
   where `NN ≈ 25-40` (six ~1500-char docs at chunk_size=800, overlap=100 → ~3-5 chunks each).

3. **Determinism check:**
   ```bash
   make ingest && cp var/index/v1.pkl /tmp/a.pkl
   rm -rf var/index
   make ingest && diff var/index/v1.pkl /tmp/a.pkl
   ```
   Expect: zero diff.

4. **Live reload:**
   ```python
   from rag.ingestion import InMemoryVectorIndex
   idx = InMemoryVectorIndex.load(Path("var/index/v1.pkl"))
   len(idx)  # → 25-40
   ```

5. **Lint / types / docs:** clean (see step 1).

---

## 6. Rollback

Trivial. The corpus is committed, but everything under `var/` is gitignored. Removing `var/` reverts the runtime state; `git revert` reverts the code. No DB migrations, no MCP contract changes, no public API surface.

---

## 7. Branch + PR

- Branch: `feature/feature-4.1-knowledge-base` (off `developer`, HEAD `f7d3d18`).
- Single PR closes both #44 (4.1.1) and #45 (4.1.2) — per user's "both in one PR" decision.
- After merge: `developer` gains the corpus + ingestion pipeline; Feature 4.2 can branch off and consume the persisted index.

---

**Awaiting sign-off.** Reply "approved" to apply, or send edits.
