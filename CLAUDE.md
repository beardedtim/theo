# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Theo is a Bible study tool: hybrid vector + full-text search over 29 English
translations, backed by a knowledge graph (people/places/events/groups),
Easton's Dictionary, STEPBible's TIPNR proper-noun gazetteer and Strong's
lexicons, and an NLP pipeline (spaCy+coref, and optionally an LLM) that
extracts entities and SVO statements per passage. FastAPI backend
(`theo/`), React/Chakra client (`client/`), Postgres via ParadeDB
(pgvector + pg_search/BM25).

## Commands

Requires [go-task](https://taskfile.dev). First time: `cp .env.example .env`.

```
task              # db + API + client dev servers together
task db:up         # just the ParadeDB container (docker compose up -d --wait)
task db:down
task db:reset       # wipe theo_pgdata volume and recreate from artifacts/init.sql (prompts)
task server         # uv run uvicorn theo.server:app --reload --port 8000
task client         # pnpm install && pnpm dev, inside client/
task test           # uv run pytest -- requires db up AND populated (see Data pipeline below)

task prod:up        # full stack from docker-compose.prod.yaml (separate compose project/db volume)
task prod:down
task prod:build
```

Single test / single file: `uv run pytest tests/test_search.py -k semantic`.
Tests are integration tests against a real, running, ingested database (`tests/conftest.py` boots the actual FastAPI app in-process) — there's no mocking of `theo.db.get_connection()`, so `task db:up` plus at least the verse/pericope ingest steps must have happened first.

Client lint: `pnpm lint` (oxlint) from `client/`. Client build: `pnpm build` (`tsc -b && vite build`).

No Python linter/formatter is configured — match existing style.

## Data pipeline

The database starts empty. `data/bible/`, `data/theographic/`, and
`data/step-bible/` are raw corpora, **not tracked in git**. Ingestion has a
strict order (later steps depend on earlier tables); see
[DEVELOPMENT.md](DEVELOPMENT.md#data-pipeline) for the full ordered command
list and what each populates. Every ingest script is idempotent/resumable —
already-present rows are skipped, so rerunning after adding a translation or
fixing `build_pericopes.py` only submits what's new.

`annotate_pericopes.py` (spaCy+fastcoref) needs the `nlp`/`gpu` uv dependency
groups and a GPU is strongly recommended (~25 min for all NIV pericopes on an
RTX 4060). `llm_annotate_pericopes.py` is the alternative/complementary
together.ai pipeline and needs `TOGETHER_API_KEY`.

## Architecture

### Database (`artifacts/init.sql`)

Schema-only-on-fresh-volume; see [DEVELOPMENT.md](DEVELOPMENT.md#database)
for the full table-by-table breakdown. The load-bearing structural choices:

- **`verses`/`pericopes` are the flat, translation-spanning source of truth.**
  `verses` is per-(translation, book, chapter, verse). `pericopes` are
  section-level passage groupings (e.g. "The Good Shepherd and His Sheep")
  that search results are grouped by, keyed by verse range and therefore
  translation-independent.
- **`reading_verses`/`reading_headings` are separate, display-only data**
  (paragraph/poetry layout, inline styling, section headings), deliberately
  not merged into `verses`/`pericopes`. NIV only for now.
- **`chunks_1024`** holds one embedded chunk per pericope, keyed by
  `embedding_model` (so multiple embedding models can coexist). The
  embedding dimension is baked into the table name/schema — changing models
  to a different dimension means editing `artifacts/init.sql` and
  rebuilding, not a config change.
- **`step_names`/`step_name_forms`/`step_name_verses`** (STEPBible TIPNR) vs
  **`people`/`places`** (Theographic knowledge graph) are two independent
  proper-noun sources with different guarantees: STEP's verse links come
  from original-language tagging (exhaustive, ground truth); Theographic's
  come from curated NER-adjacent tagging. `theo/metadata.py` merges them
  with STEP taking priority (`ENTITY_SOURCES`) — see below.
- **`pericope_annotations`** stores NLP output keyed by a `pipeline` string
  prefix (`"together:"` for the LLM pipeline, `"en_core_web..."` for spaCy),
  so reprocessing under a new model/version coexists with old rows instead
  of overwriting them.
- **`notes`** holds personal commentary: hand-written markdown files with
  YAML frontmatter under `notes/` (tracked in git, unlike `data/`), synced
  in by `ingest_notes.py` via `theo/notes.py`. Anchored to a verse range
  like `pericopes`/`events`, searchable (BM25) and included in `/metadata`
  and the hybrid-search metadata leg. Unlike every other ingest script,
  the folder is the live source of truth: rerunning after an edit
  overwrites the row (upsert by slug = file path). Deleting a file only
  deletes its row if you rerun with `--prune`, since pruning trusts
  whatever directory you point it at to be the *complete* set.
- To add tables to an already-running dev DB without a full reset, apply
  just the new DDL by hand — most `CREATE INDEX` statements in
  `init.sql` lack `IF NOT EXISTS`, so replaying the whole file throws noisy
  errors for everything that isn't new.

### `theo/search.py` — the search fusion logic

Three modes, all returning the same `SearchResult` shape:
- `semantic_search` — cosine similarity, query embedding vs. `chunks_1024`.
- `bm25_search` — pg_search BM25 over chunk raw text.
- `hybrid_search` — reciprocal rank fusion across **three** rankings: the
  two above *plus* `metadata_search` (BM25 over `pericope_metadata_index`,
  a denormalized blob of STEP/theographic entity names + NLP-extracted
  SVO/entities/themes/keywords/summary). This third leg is what lets a
  query match a passage's subject matter even when the query words never
  appear in the verse text itself. Semantic and chunk-BM25 stay pure/
  standalone; only hybrid gets the metadata leg. Rankings are fused by rank
  (not raw score) since the three live on unrelated scales.
- Free-text user input going into any `@@@` (pg_search) query MUST go
  through `theo/bm25.py`'s `sanitize_query` first — pg_search's right-hand
  side is parsed as tantivy query syntax, and unescaped user input (an
  apostrophe, a colon, a bare trailing `AND`) is a parse error that
  surfaces as an HTTP 500 otherwise.

### `theo/metadata.py` — one-call passage assembly

`/metadata/*` exists so the client doesn't have to fan out over
`/people`, `/places`, `/events`, `/names`, `/lexicon`, etc. Where multiple
sources describe the same thing it returns **one prioritized answer**, not
parallel per-source lists:
- Entities: merged per-(kind, name) across `ENTITY_SOURCES` priority order
  (STEP/TIPNR first, Theographic filling gaps).
- NLP annotation: one per pericope, best pipeline per `ANNOTATION_PIPELINES`
  (LLM enrichment first, spaCy fallback).

To promote a new source/pipeline, add it to the front of the relevant
priority tuple — everything below becomes a fallback automatically. The
unprioritized per-source data is still reachable via the per-source
endpoints.

### API surface (`theo/server.py`)

FastAPI app `theo.server:app`. Route params follow one consistent range
shape everywhere a verse range is addressed —
`{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}` — matching
the shape of a `pericope`/search-result object, so the client can pass a
result's range straight into `/people`, `/places`, `/events`, `/names`,
`/metadata`, `/reading` without reshaping it. `book` accepts either a
number or a name everywhere. Full endpoint-by-endpoint reference:
[DEVELOPMENT.md](DEVELOPMENT.md#api). Interactive docs at `/docs` when
running.

`theo/db.py` provides a process-wide pooled connection
(`get_connection()`); don't open ad hoc `psycopg.connect()` calls in new
module code — follow the existing per-module query-function pattern (see
any of `theo/people.py`, `theo/events.py`, etc.) instead.

### Client (`client/`)

Vite + React 19 + TypeScript, Chakra UI, wouter for routing. Pages live in
`client/src/pages/`, talk to the API via `client/src/lib/api.ts`
(`http://localhost:8000` by default, override with `VITE_API_BASE_URL`).
Passage cards on `/search` and `/verses` share a pattern: a collapsible
"passage details" panel that lazily fires a single `/metadata` call (by
pericope id or verse range) and renders everything it returns — new detail
UI for a passage should extend that panel rather than adding new per-source
API calls from the page component.

### Production (`docker-compose.prod.yaml`)

Separate Compose project (`theo-prod`) from dev, with its own
`theo_pgdata` volume — starting it does **not** inherit dev's ingested
data. After `task prod:up`, the data pipeline must be re-run pointed at the
prod db (`scripts/prod-ingest.sh` handles the `POSTGRES_HOST` override).
`scripts/export-db.sh` / `scripts/import-db.sh` move a full dump between
dev and prod (`backups/`, gitignored).
