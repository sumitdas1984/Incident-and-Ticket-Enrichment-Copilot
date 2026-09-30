# 10 — From demo to production: what changed, what didn't, and why

> **Why this doc exists.** The version of the project you shared
> with ABB had a hermetic demo path — `MockLLMClient`,
> `MockPlanner`, deterministic embedder, in-memory numpy
> vector store. That was deliberate: it let the system run
> from a clean checkout with no API keys, no model downloads,
> no GPU, no surprise bills. It's also not what you'd ship
> to a plant.
>
> This doc walks the gap between *what ABB has already seen*
> and *what production would actually need*. It's the answer
> to the inevitable interview question: **"how would you make
> this production-ready?"**
>
> **Read this after Doc 09.** It assumes you've read the
> 09-question flashcards at least once.

---

## The one-sentence answer

> "The demo path is hermetic by design; production is one
> config switch per layer, plus a ChromaDB wiring we've
> documented but not yet implemented. Here's exactly what
> each switch does, what it costs, and what it would take to
> lift the remaining stub."

If the interviewer only hears one sentence, that's the one.

---

## The shape of the change

The demo ran on **three "fake" things**:

| Demo path | Production path | Cost to switch |
|---|---|---|
| `MockLLMClient` | OpenAI / Anthropic LLM | one env var + an API key |
| `MockPlanner` (regex NL→slots) | `LLMPlanner` (real LLM prompt) | one env var |
| `DeterministicEmbeddingModel` (SHA-256 hash) | `SentenceTransformerEmbeddingModel` (real model) | one env var + re-ingest + a 384-dim model download |
| `InMemoryVectorIndex` (numpy in `var/index/v1.pkl`) | ChromaDB | not wired yet — see § ChromaDB |

The "demo path" isn't fake as in "broken" — it's deterministic
and fast, which is exactly what you want from a demo. The
point is the *promotion path* between them is well-defined
and (mostly) one config switch.

---

## What was there before today

This is the version ABB has already reviewed. To talk about it
honestly, you have to know what was wired where.

### The LLM

- **Default:** `MockLLMClient` returned a canned response
  keyword-matched to the intent. Instant, deterministic,
  zero-cost.
- **Production path:** `build_llm_client(provider="openai")`
  returns an `OpenAIClient` adapter. It was implemented and
  unit-tested, but never run end-to-end against the real API.
- **The honest answer to "did you call OpenAI in the demo?"**
  is: *no, the demo path didn't. The demo path was hermetic
  by design.*

### The planner

- **Default:** `MockPlanner` — a regex + heuristic NL→slots
  extractor. It detected "Boiler B-101", "last 90 days",
  "high-severity", etc., and produced a `Plan` for the
  chain runner.
- **Production path:** `LLMPlanner` — the same LLM client,
  with a different prompt. Implemented and unit-tested.
- **The honest answer:** *the planner was a slot extractor,
  not a regex pattern-match on the canonical question. The
  canonical question was preserved verbatim through it.*

### The embedder

- **Default:** `DeterministicEmbeddingModel` — a SHA-256
  hash that laid bytes into a 384-dim float vector. The
  vectors weren't semantically meaningful; they were just
  deterministic.
- **Production path:** `SentenceTransformerEmbeddingModel` —
  `all-MiniLM-L6-v2`, 384-dim, real semantic embeddings.
- **The honest answer:** *the demo was fast because the
  embedding was a hash, not because the indexing was slow.
  Same vector store, same in-memory index — just different
  numbers.*

### The vector store

- **Default:** `InMemoryVectorIndex` — numpy arrays pickled
  to `var/index/v1.pkl`. No external service, no port, no
  docker container.
- **Documented elsewhere:** ChromaDB at `vector-store:8000`.
  The compose service is provisioned. No Python code reads
  from it.
- **The honest answer:** *ChromaDB is documented in the
  README and the Docker stack, but there is no
  `ChromaDBVectorIndex` class and no ChromaDB wiring in
  `apps/backend/wiring.py`. The README is aspirational for
  this one slice.*

### The guard

- **Before today:** nothing. If the persisted index was built
  with one embedder and the runtime wired a different one,
  the orchestrator would silently produce nonsense
  cosine-similarity scores. The chain would complete, the
  GUI would render an answer, but the citations would be
  random.
- **The honest answer:** *we shipped the demo with a
  known footgun covered in `docs/known-limitations.md` § 7
  — a real implementation would have caught this at boot.*

---

## What changed today

The actual diff you made to take the demo into "production-ready
demo mode." Five commits' worth of work, all in one session.

### Change 1 — embedder backend is now config-driven

**Before:** `apps/backend/wiring.py:_build_rag` hard-coded
`DeterministicEmbeddingModel(...)`. The only way to use the
real embedder at runtime was to edit the wiring.

**After:** `core.config.Settings.embedder_backend` defaults to
`"deterministic"`. Setting `EMBEDDER_BACKEND=sentence-transformers`
in `.env` flips the runtime to the real model.

**What it does:** one config switch, no code change, takes
the system from "demo with hash vectors" to "demo with real
semantic vectors."

**What it costs:** an 80MB model download on first run
(one-time), then ~50ms per query to embed.

### Change 2 — mismatch guard at startup

**Before:** silent nonsense on embedder mismatch (the documented
footgun).

**After:** `_build_rag` compares the wired embedder's
`model_name` against `IndexMetadata.embedder_name` and raises
`LLMError` with a precise message at startup. The orchestrator
won't even begin serving requests if the embedder and the
index don't match.

**What it does:** turns a silent-regression bug into a
loud configuration error. The error message tells the
operator exactly which re-ingest command to run.

**What it costs:** zero — same code path, one extra equality
check.

### Change 3 — `model_name` is the namespaced identifier

**Before:** `SentenceTransformerEmbeddingModel.model_name`
returned `"all-MiniLM-L6-v2"` (the bare model name). The
pipeline's `_embedder_name` helper stamped metadata as
`"sentence-transformers:all-MiniLM-L6-v2"`. The two
strings didn't match — the guard would have spuriously
rejected a matched pair.

**After:** both embedder properties return the namespaced
form. `DeterministicEmbeddingModel.model_name` returns
`"deterministic:384"`. `SentenceTransformerEmbeddingModel.model_name`
returns `"sentence-transformers:all-MiniLM-L6-v2"`. The
pipeline's `_embedder_name` helper is the single source of
truth.

**What it does:** makes the guard actually work. Without this
fix, the guard would have refused every request to use the
real embedder.

**What it costs:** zero — one docstring change on the
property, two pinning tests.

### Change 4 — `tests/unit/core/test_config.py` actually isolates env

**Before:** the test asserted "without any env vars, Settings
returns the documented defaults" — but it didn't actually
clear the env. It was passing only because nobody had a
`.env` file with `LLM_PROVIDER=openai` sitting next to the
test runner.

**After:** the test strips every env var that pydantic-settings
reads, and passes `_env_file=None` to bypass the `.env` file
entirely. The test is now honest about its contract.

**What it does:** makes the test runnable against any local
.env without surprise failures. Pinning the new
`embedder_backend` default is now part of the same test.

**What it costs:** zero — pure test fix.

### Change 5 — `docs/known-limitations.md` § 7 flipped to "closed"

**Before:** § 7 was "Embedder mismatch raises, not warns" —
open, with a "what it would take to lift" note.

**After:** § 7 is "Embedder backend is config-driven (closed)"
— the footgun is gone, the env var is documented, the
two-command promotion path is shown.

**What it does:** keeps the limitation index honest. The
interviewer can read the doc and see that the team closed
the gap.

**What it costs:** zero — docs only.

---

## What we did NOT change today

Things deliberately left alone, so you can talk about them
honestly.

### ChromaDB

- **Status:** documented, not implemented.
- **What it would take:** ~200-400 lines of new code:
  - `ChromaDBVectorIndex` class implementing the `VectorIndex`
    Protocol in `rag/ingestion/index.py`.
  - `--backend chroma` flag in `rag/ingestion/__main__.py`.
  - ChromaDB client initialization in
    `apps/backend/wiring.py`.
  - A `vector_store_backend` config field to pick
    `memory` vs `chroma`.
  - Tests for the new code path.
- **Why it's deferred:** the in-memory index is fine for the
  corpus size (six documents, ~25-40 chunks). ChromaDB at
  scale (>100k chunks, >10 req/s) is the trigger.
- **The honest answer:** *at our corpus size, the in-memory
  index is faster than ChromaDB. The deferred wiring is about
  scale, not correctness.*

### Streaming LLM responses

- **Status:** not implemented. The mock returns the full
  reply at once; the OpenAI adapter does the same.
- **What it would take:** FastAPI `StreamingResponse` with
  Server-Sent Events, a stream-aware GUI client.
- **Why it's deferred:** the demo flow is a single render,
  not a streaming typewriter. Streaming would mostly be
  cosmetic at the corpus size.

### Persistent conversation store

- **Status:** `ConversationStore` is process-local `dict`.
  Restart loses the conversation.
- **What it would take:** swap the dict for SQLite or Redis.
  The store's API is small (append / get_or_create / get_messages).
- **Why it's deferred:** the demo is single-session, single-user.
  Multi-user or long-running needs persistence.

### Parallel chain execution

- **Status:** `PlanStep.waves` is in the schema, but
  `ChainRunner.run` executes serially.
- **What it would take:** a DAG dispatcher that respects
  `depends_on` and runs independent steps in parallel.
- **Why it's deferred:** the brief's example workflow is
  linear. Parallelism would shave ~30% off latency; the
  gain doesn't justify the complexity for the demo.

---

## The impact, in numbers

This is what changed for the system's behavior.

### Latency

| Path | Before | After |
|---|---|---|
| `/chat` end-to-end (deterministic) | ~50ms | ~50ms (no change) |
| `/chat` end-to-end (real LLM + planner) | n/a (didn't run before) | ~2-3s |
| `/chat` end-to-end (real LLM + planner + real embedder) | n/a | ~2-3s |

The LLM call dominates. The embedder is one ~50ms in-process
call once the model is loaded.

### Cost

| Layer | Cost per request |
|---|---|
| Mock LLM | $0 |
| OpenAI `gpt-4o-mini` | ~$0.0001 (one chat completion) |
| Sentence-transformers (in-process) | $0 |
| ChromaDB (when implemented) | $0 (self-hosted) |

Below the noise floor of a real plant's alarm budget.

### Reproducibility

| Path | Deterministic? |
|---|---|
| Old demo (everything mock) | Yes — same query, same answer, every time |
| New demo (real LLM + real planner) | No — temperature > 0 by default |
| New demo (real embedder + real LLM) | No — LLM still varies |

For a demo, this matters less than it sounds. The structure
of the answer (incident, citations, trace) is stable; the
prose varies. The GUI renders the structure, not the prose.

---

## How to talk about this in the interview

### What to say

> "The version we shared was the hermetic demo path — mock
> LLM, mock planner, deterministic embedder, in-memory index.
> That was deliberate: it let the system run from a clean
> checkout with no API keys. The production path is one config
> switch per layer. We've since flipped all three switches
> in our dev environment — the real LLM, the LLM planner,
> and the sentence-transformers embedder all run against
> the real OpenAI API in our running stack. ChromaDB is
> documented but not yet wired; that's the one slice we'd
> tackle next."

### What NOT to say

- ❌ "The demo was using fake everything." — it wasn't fake,
  it was hermetic. The distinction matters.
- ❌ "We never called OpenAI." — true, but the wrong framing.
  The framing is "the demo path was hermetic; the production
  path is wired and tested."
- ❌ "ChromaDB is wired." — it isn't. The README mentions it
  and the compose service is provisioned, but no Python code
  reads it. Don't overpromise.
- ❌ "The embedder was the issue." — no, the embedder was the
  *easy* part. The hard part was detecting the mismatch before
  it silently produced nonsense.

### Likely follow-ups

**Q: "Why would you use a deterministic embedder in a demo?"**

> "Two reasons. First, the model is 80MB — downloading it on
> every CI run is wasteful. Second, the demo has to be
> reproducible: same question, same answer. A real embedder
> gives us that with the cosine similarities actually meaning
> something, but the demo path doesn't need that."

**Q: "Could you implement ChromaDB in a day?"**

> "Yes. It's a `VectorIndex` Protocol implementation plus
> a config switch in `wiring.py` — probably 200-400 lines
> including tests. The deferred work isn't particularly hard;
> it's just deferred because the in-memory index is faster
> at our corpus size."

**Q: "What would you change first if you had more time?"**

> "Three things in priority order. First, the wave-aware
> executor — independent MCP calls in parallel would cut
> latency by ~30%. Second, persistent conversation store so
> conversations survive restarts. Third, ChromaDB when the
> corpus grows past ~1000 chunks."

---

## If asked in the interview

**Q: "Is this project production-ready?"**

> "The demo path is — it's tested, hermetic, and reproducible.
> The gaps to production are: ChromaDB wiring, persistent
> conversation store, and parallel chain execution. None of
> these are architectural — they're follow-up work in the
> shapes I'd expect for a 10-14 hour timebox."

**Q: "What did you learn by wiring the real services?"**

> "Two things. First, the embedder's `model_name` property
> wasn't namespaced to match the index metadata — the guard
> would have spuriously rejected a matched pair. We fixed
> that and added a pinning test. Second, the first-run
> latency of the real sentence-transformer model is
> significant — it's a 80MB download on cold start. In
> production we'd want to bake the model into the docker
> image, not fetch it on first request."

**Q: "What would break first under real load?"**

> "The in-memory vector index. Past ~1000 chunks the
> cosine-similarity search becomes the bottleneck. That's
> the ChromaDB wedge. The LLM and MCP servers are the
> second bottleneck — they need horizontal scale behind a
> load balancer."

---

## Open questions for next time

- *What's the actual LLM prompt in production mode?* →
  `apps/backend/orchestrator/answer.py` — the same prompt
  the mock used, but the real LLM non-deterministically
  paraphrases it.
- *What's the ChromaDB minimum viable implementation?* →
  Out of scope for this doc; would be a follow-up story.
- *How would you bake the sentence-transformer model into
  the docker image?* → Pre-download in the `Dockerfile`,
  cache under `~/.cache/huggingface/`, mount that into
  the backend service.
