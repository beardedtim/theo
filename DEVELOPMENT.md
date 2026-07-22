# Development

This is the detailed reference for working on Theo. For the high-level pitch
and the quickstart, see [README.md](README.md).

## Individual pieces

`task` (see [README.md](README.md#development)) runs the db, API, and client
together. If you'd rather run them by hand:

| Task             | Does                                                           |
| ---------------- | --------------------------------------------------------------- |
| `task db:up`     | `docker compose up -d --wait`                                   |
| `task server`    | `uv run uvicorn theo.server:app --reload --port 8000`           |
| `task client`    | `pnpm install && pnpm dev` inside `client/`                     |
| `task db:down`   | `docker compose down`                                           |
| `task db:reset`  | Wipe the `theo_pgdata` volume and recreate it (prompts first)   |
| `task test`      | `uv run pytest` — runs the API test suite against the db        |

## Production

Builds (on first run) and starts the whole stack from
[docker-compose.prod.yaml](docker-compose.prod.yaml): ParadeDB, the API
([Dockerfile.api](Dockerfile.api)), the built client served by nginx
([client/Dockerfile](client/Dockerfile)), and an nginx reverse proxy
([proxy/nginx.conf](proxy/nginx.conf)) that's the single entrypoint on
`http://localhost` — `/api/*` goes to the API (prefix stripped), everything
else goes to the client. TLS isn't handled here; put something in front of
this proxy for that.

| Task               | Does                                                 |
| ------------------ | ----------------------------------------------------- |
| `task prod:up`      | `docker compose -f docker-compose.prod.yaml up -d`     |
| `task prod:down`    | `docker compose -f docker-compose.prod.yaml down`      |
| `task prod:build`   | Rebuild the API and client images                      |

Uses the same `.env` as dev. This stack is a separate Compose project
(`theo-prod`) from the dev `docker-compose.yml`, so the two can run side by
side without colliding, but they don't share a database — `task prod:up`
starts against a fresh `theo_pgdata` volume, so the [data pipeline](#data-pipeline)
below needs to be re-run (pointed at `POSTGRES_HOST=db` inside the `api`
container, or `localhost` with the port published) to populate it.

## Database

`docker compose up -d` (or `task db:up`) starts a ParadeDB
(`paradedb/paradedb:0.24.3-pg18`) container on `localhost:5432` and, on first boot,
runs [artifacts/init.sql](artifacts/init.sql), which creates:

- **`verses`** — one row per (translation, book, chapter, verse), with an HNSW
  index (`vector_cosine_ops`) on an `embedding vector(1024)` column for semantic
  search and a BM25 index (`pg_search`) on `text`/`book`/`translation` for keyword
  search.
- **`pericopes`** — section-level passages (e.g. "The Good Shepherd and His
  Sheep") spanning a verse range, used as the unit search results are grouped by.
- **`chunks_1024`** — one embedded chunk per pericope, keyed by `embedding_model`
  so multiple models' vectors can coexist. `chunks_1536` also exists in the schema
  for a future higher-dimensional model but currently only holds placeholder data.
- **`people`** / **`places`** — named individuals and locations from the
  [Theographic Bible Metadata](https://theographic.bible) knowledge graph, each with
  a BM25 index for keyword search. `people` also carries `mother_id`/`father_id`/
  `birth_place_id`/`death_place_id` self/cross-references and a `person_relationships`
  join table for siblings/half-siblings/partners.
- **`verse_people`** / **`verse_places`** — which people/places are mentioned in a
  given `(book, chapt_num, verse_num)`, translation-independent like `pericopes`.
- **`people_groups`** — named collections of people (tribes, apostles, genealogies...),
  with a `parent_group_id` self-reference and a `people_group_members` join table.
- **`passage_groups`** / **`passage_group_members`** / **`passage_group_aliases`** —
  canon-structure groups (Pentateuch, Old/New Testament, Gospels...): which books belong
  together. Distinct from `people_groups` (people, not passages). Hand-authored in
  [passage_groups.yaml](passage_groups.yaml) (tracked in git, like `notes/`), synced by
  `ingest_passage_groups.py`. `parent_group_id` is display/breadcrumb hierarchy only;
  every group (leaf and container) restates its own full book coverage in
  `passage_group_members`, so "which groups contain book N" is a flat range scan with
  no tree walk, and ordering by range width gives specific-before-general for free.
  `passage_group_aliases` holds alternate names (`Torah`, `The Twelve`, `OT`...), keyed
  by a normalized (lower/trim) lookup column that's `UNIQUE` across all groups. See
  [theo/passage_groups.py](theo/passage_groups.py).
- **`events`** — biographical/historical events (e.g. "Exodus from Egypt"), with a
  `predecessor_id` self-reference, a `sort_key` for chronological ordering across
  BC/AD dates, and `event_parts`/`event_people`/`event_places`/`event_groups`/
  `event_verses` join tables for how an event relates to other events, its
  participants, locations, groups, and the verses that describe it.
- **`dictionary_entries`** — Easton's Bible Dictionary (1897), BM25-indexed on
  `term`/`entry_text`, with `dictionary_entry_people`/`dictionary_entry_places`
  join tables cross-linking entries to the people/places they define.
- **`reading_verses`** / **`reading_headings`** — paragraph/poetry-line layout,
  inline styling (smallcaps/italic/bold/red-letter), and section headings for the
  reading view, parsed from jburson/bible-data's per-word markup. Deliberately
  separate from `verses`/`pericopes` (which stay the flat/raw source of truth for
  search and the theographic verse-range joins) — this is display-only data.
  NIV only for now; see [theo/reading.py](theo/reading.py).
- **`step_names`** / **`step_name_forms`** / **`step_name_verses`** — STEPBible's
  [TIPNR](https://github.com/STEPBible/STEPBible-Data) proper nouns: every person,
  place, month, deity etc. as one row per distinct individual/location with a
  Strong's-derived `ustrong` id, prose descriptions/articles, every name form
  (Hebrew/Greek script, disambiguated Strong's, ESV/KJV/NIV renderings), and an
  exhaustive per-verse occurrence list derived from the original-language
  tagging — unlike NER over translated text, these verse links are ground truth.
  See [theo/step_names.py](theo/step_names.py).
- **`step_lexicon`** — STEPBible's brief Strong's lexicons (TBESH Hebrew /
  TBESG Greek): one row per disambiguated Strong's number with the original-
  language lemma, transliteration, morphology code, one-word gloss, and a brief
  meaning (Abridged BDB / Abbott-Smith), BM25-indexed. The `ustrong` column ties
  entries to `step_names.ustrong` and to the gazetteer ids in
  `pericope_annotations` — e.g. Aaron's `H0175` fans out to both the Hebrew
  entry and its Greek form Ἀαρών. See [theo/lexicon.py](theo/lexicon.py).
- **`pericope_annotations`** — NLP metadata per (pericope, translation): NER
  entities (carrying `ustrong` ids for gazetteer matches), (subject, verb,
  object) triples, and coreference-resolved text, produced by the
  spaCy (`en_core_web_trf`) + fastcoref pipeline in [theo/parse.py](theo/parse.py).
  Keyed by a `pipeline` version string so reprocessing under new models can
  coexist with old rows.
- **`notes`** — personal commentary: BM25-indexed, synced from hand-written
  markdown files under `notes/` (see [theo/notes.py](theo/notes.py) and
  the Notes section below). This is the one table where the source
  folder, not the database, is authoritative — `ingest_notes.py` upserts
  on edit and deletes rows whose file is gone. A note is scoped to
  *either* a verse range (`book`/`chapter_start`/... — all nullable, and
  all-or-nothing via the `notes_scope_xor` check constraint) *or* a
  `passage_group_id`, never both. `attributes` (JSONB) holds optional
  key/value facts that inherit down to anything inside the note's scope —
  see `theo.metadata.resolve_attributes`.

`embedding`'s dimension (1024) must match whatever embedding model is used for
ingestion — decide before first ingesting data; changing it later means editing
[artifacts/init.sql](artifacts/init.sql) and rebuilding, not just a config change.

Schema only runs against a fresh volume. To reset during development:

```
task db:reset
# or: docker compose down -v && docker compose up -d --wait
```

To add new tables to an _already-running_ dev DB without a full reset (e.g.
after pulling a migration that only appends `CREATE TABLE IF NOT EXISTS`
statements to `artifacts/init.sql`), apply just the new DDL directly rather
than re-running the whole file — most of its `CREATE INDEX` statements lack
`IF NOT EXISTS`, so replaying it wholesale throws noisy (if harmless)
"already exists" errors for everything that isn't new:

```
docker compose exec -T db psql -U theo -d theo <<'SQL'
<the new CREATE TABLE / CREATE INDEX statements>
SQL
```

Connect from Python via [theo/db.py](theo/db.py):

```python
from theo.db import get_connection

with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM verses")
        print(cur.fetchone())
```

## Data pipeline

`data/bible/<TRANSLATION>/` holds the raw corpus (not tracked in git) — each
translation has the verse text as a combined JSON, and per-book JSON files.
`data/info/` (a clone of jburson/bible-data) supplies NIV section headings used
to derive pericope boundaries, and also the per-word paragraph/poetry/styling
markup ingested into `reading_verses`/`reading_headings` for the reading view.
`data/theographic/` (a clone of
[theographic-bible-metadata](https://theographic.bible), also not tracked in git)
supplies the `people`/`places`/`people_groups`/`events`/`dictionary_entries`
knowledge-graph data — its `json/` folder is the source of truth (preferred over
its `CSV/` folder, which doesn't follow normal table design).

Ingestion, in order:

```
uv run ingest_verses.py data/bible/NIV/NIV_bible.json --translation NIV
uv run build_pericopes.py                          # writes data/pericopes.json
uv run ingest_pericopes.py data/pericopes.json
uv run embed_pericopes.py --translation NIV         # populates chunks_1024

uv run ingest_places.py                             # populates places, verse_places
uv run ingest_people.py                              # populates people, person_relationships, verse_people
                                                       # (run after ingest_places.py: resolves birth/death place)
uv run ingest_people_groups.py                       # populates people_groups + members/verses
                                                       # (run after ingest_people.py)
uv run ingest_events.py                              # populates events + parts/people/places/groups/verses
                                                       # (run after ingest_people_groups.py)
uv run ingest_dictionary.py                          # populates dictionary_entries + person/place links
                                                       # (run after ingest_people.py/ingest_places.py)

uv run ingest_reading.py                              # populates reading_verses, reading_headings (NIV only)
                                                       # (independent of the theographic/pericope steps above)

uv run ingest_step_names.py                           # populates step_names + forms/verse links from
                                                       # data/step-bible's TIPNR file (independent of the above)
uv run ingest_lexicon.py                              # populates step_lexicon from data/step-bible's
                                                       # TBESH/TBESG brief lexicons (independent of the above)
uv run annotate_pericopes.py                          # populates pericope_annotations via spaCy + fastcoref
                                                       # (needs verses + pericopes; GPU strongly recommended --
                                                       # ~25 min for all NIV pericopes on an RTX 4060, resumable)
uv run llm_annotate_pericopes.py                      # populates pericope_annotations via together.ai (entities,
                                                       # SVO, themes, keywords, summary; needs TOGETHER_API_KEY)

uv run ingest_passage_groups.py passage_groups.yaml   # syncs the canon-structure taxonomy (Pentateuch, Old/New
                                                       # Testament, ...) into passage_groups/passage_group_members
                                                       # -- independent of the above; run before ingest_notes.py
                                                       # if any note frontmatter references a group by slug
uv run ingest_notes.py                                # syncs notes/*.md into the `notes` table (independent of
                                                       # the above except passage_groups if a note uses `group:`;
                                                       # rerun any time after adding/editing/deleting a note file
                                                       # -- see the Notes section below)

uv run index_pericope_metadata.py                     # populates pericope_metadata_index -- STEP/theographic
                                                       # entity names+descriptions, personal notes, and the NLP
                                                       # annotation's SVO/entities/themes/keywords/summary,
                                                       # denormalized into one BM25-searchable text blob per
                                                       # pericope. theo.search's hybrid mode fuses hits against
                                                       # it alongside chunk-text BM25 and semantic similarity.
                                                       # Rerun after any of the STEP/theographic/annotation/notes
                                                       # steps above change.
```

## Passage groups (canon structure)

`passage_groups.yaml` (repo root, tracked in git) is a small hand-authored
taxonomy of which books belong together -- Pentateuch, Old/New Testament,
Gospels, Pauline/General Epistles, and so on -- and how those groupings
nest. Each entry is a `slug`/`name`/optional `description`/optional
`parent` (another group's slug, display hierarchy only), plus either
`books: [book_start, book_end]` for a contiguous range or `members: [...]`
for an explicit, possibly non-contiguous book list (e.g. Johannine
literature: John + 1/2/3 John + Revelation). An optional `aliases:` list
gives alternate names that resolve to the group in lookups (`Torah` ->
pentateuch, `The Twelve` -> minor-prophets), stored in
`passage_group_aliases`. Aliases match case-insensitively / whitespace-
trimmed, are globally unique, and may not collide with any slug or book
name -- ingest **hard-fails** (before writing anything) on a collision or
duplicate rather than silently picking a winner. See the file itself for
the full seed taxonomy -- it's a starting point, not exhaustive.

Sync with `uv run ingest_passage_groups.py passage_groups.yaml`. Like
notes, this treats the file as live/authoritative: editing a group and
rerunning overwrites it in place (name, description, parent, book ranges,
aliases). `--prune` additionally removes groups no longer in the file
(off by default, same rationale as `ingest_notes.py --prune`).

Groups show up in `/passage-groups` and `/passage-groups/{slug}` (which
accepts a slug, canonical name, or any alias, and returns the group's
`aliases`), and in `/metadata`'s `passage_groups` field (which groups a
range's book belongs to, narrowest first) -- see
[theo/passage_groups.py](theo/passage_groups.py).

## Notes (personal commentary)

`notes/` holds hand-written markdown files -- tracked in git, unlike
`data/` -- for commentary that corrects or supplements Theographic's more
theologically conservative framing (dating, historicity, authorship,
etc.) with your own research. Organize them into subfolders however you
like; a note's identity (its `slug`) is its path relative to `notes/`,
without the `.md` extension.

Each file is YAML frontmatter, a closing `---`, then a markdown body. A
note is scoped to *either* a verse range *or* a passage group -- never
both. Range-scoped, the common case:

```markdown
---
title: "Dating the Exodus: what the archaeological record actually supports"
book: Exodus
chapter_start: 1
verse_start: 1
chapter_end: 15
verse_end: 21
tags: [historicity, archaeology, dating]
---
Body text in markdown goes here.
```

`book` accepts a number or a name. The verse range can be given in three
shapes, from most to least explicit -- pick whichever fits:

- `chapter_start`/`verse_start`/`chapter_end`/`verse_end` -- a range spanning chapters
- `chapter`/`verse_start`/`verse_end` -- a range within one chapter
- `chapter`/`verse` -- a single verse

Group-scoped, using a [passage_groups.yaml](passage_groups.yaml) slug
instead of `book`/a range:

```markdown
---
title: "Authorship of the Pentateuch"
group: pentateuch
tags: [authorship, historicity]
attributes:
  author: "Disputed -- traditionally attributed to Moses; the Documentary Hypothesis proposes composite JEDP authorship."
---
Body text in markdown goes here.
```

`tags` is optional (defaults to none). `attributes` is optional too -- a
flat map of key/value facts (author, date, genre, ...) that *inherit*
down to every book/range inside the note's scope: a fact set on
`group: pentateuch` surfaces in `/metadata` for Genesis through
Deuteronomy unless a more specific note (or narrower group) sets the same
key, in which case the more specific source wins (see
`theo.metadata.resolve_attributes`). See
[notes/exodus/dating-and-historicity.md](notes/exodus/dating-and-historicity.md)
and [notes/pentateuch/authorship.md](notes/pentateuch/authorship.md) for
filled-out examples of each scope.

Sync the folder into the database with `uv run ingest_notes.py` (after
`ingest_passage_groups.py`, if any note frontmatter references a group by
slug). Unlike every other ingest script, this treats the folder as
live/authoritative: rerunning after adding or editing a file
inserts/updates its row. Deleting a note file does *not* delete its row
unless you also pass `--prune` (`uv run ingest_notes.py --prune`) --
pruning compares against whatever directory you point it at, so running
it against a partial/wrong path would silently delete every note outside
that path; only use it against your real, complete `notes/` folder when
you've actually removed a file. After syncing, rerun
`uv run index_pericope_metadata.py` so hybrid search picks up the change.

Notes show up in `/metadata` and `/metadata/pericope/{id}` (alongside
people/places/events/annotations, and via `attributes` if inherited from
a group), are searchable directly via `GET /notes?q=`, and their
title/tags are one leg of what `hybrid_search` fuses over (a note's body
is not indexed there -- see [theo/metadata_index.py](theo/metadata_index.py)
-- to avoid a long or wide-ranging note swamping every pericope in its
scope; the note itself is still reachable in full via `/notes`/`/note/{slug}`).

Every ingest script is safe to rerun — rows already present are left alone
(duplicates skipped), so re-running after adding a new translation or fixing
`build_pericopes.py`'s output only submits what's new.

Currently ingested: all 66 books' NIV verses, ~2,200 pericopes, one
`BAAI/bge-large-en-v1.5` embedding per pericope, the full Theographic
`people`/`places` knowledge graph (~3,067 people, ~1,274 places), 23 people
groups, 450 events, all 6,519 Easton's Dictionary entries with their verse
mentions and cross-links, NIV reading-formatted text (~31,100 verses,
~3,300 headings), all 4,259 TIPNR proper nouns (~35,500 verse links), all 22,717 brief-lexicon
entries (11,682 Hebrew + 11,035 Greek), NLP annotations for every NIV
pericope (both the spaCy and together.ai pipelines), and a metadata search
index built from all of the above for every NIV pericope.

## API

[theo/server.py](theo/server.py) is a FastAPI app (`theo.server:app`) exposing:

| Endpoint                                                                                    | Purpose                                                                                                                                                                             |
| ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /health`                                                                               | Liveness check                                                                                                                                                                      |
| `GET /search?q=&mode=&limit=&translation=`                                                  | Search pericopes by natural-language query. `mode` is `semantic`, `bm25`, or `hybrid` (reciprocal rank fusion of both)                                                              |
| `GET /verses/{book}/{chapter}`                                                              | Every verse in a chapter                                                                                                                                                            |
| `GET /verses/{book}/{chapter}/{verse_start}/{verse_end}`                                    | A verse range within a chapter                                                                                                                                                      |
| `GET /pericopes`                                                                            | List pericopes, optionally filtered by `book` and/or full-text `q` over titles                                                                                                      |
| `GET /pericopes/{book}`                                                                     | Every pericope in a book                                                                                                                                                            |
| `GET /pericope/{pericope_id}`                                                               | A single pericope with its full verse text                                                                                                                                          |
| `GET /people/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}`                | People mentioned in a verse range                                                                                                                                                   |
| `GET /places/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}`                | Places mentioned in a verse range                                                                                                                                                   |
| `GET /events`                                                                               | All events, in chronological order                                                                                                                                                  |
| `GET /events/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}`                | Events mentioned in a verse range                                                                                                                                                   |
| `GET /event/{event_id}`                                                                     | A single event with its participants and locations resolved                                                                                                                         |
| `GET /people-groups`                                                                        | All people groups (tribes, apostles, genealogies...)                                                                                                                                |
| `GET /people-groups/{group_id}`                                                             | A single people group with its members resolved                                                                                                                                     |
| `GET /passage-groups`                                                                        | All canon-structure groups (Pentateuch, Old/New Testament, Gospels...)                                                                                                              |
| `GET /passage-groups/{slug}`                                                                 | A single passage group with its expanded book list and direct child groups                                                                                                         |
| `GET /dictionary?q=&limit=`                                                                 | Search Easton's Bible Dictionary by term/definition (BM25)                                                                                                                          |
| `GET /dictionary/{entry_id}`                                                                | A single dictionary entry                                                                                                                                                           |
| `GET /names?q=&limit=`                                                                      | Search TIPNR proper nouns by name/description (BM25)                                                                                                                                |
| `GET /names/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}`                 | Proper nouns occurring in a verse range (exhaustive, from original-language tagging)                                                                                                |
| `GET /name/{name_id}`                                                                       | A single proper noun with its name forms, article, and full verse reference list                                                                                                    |
| `GET /lexicon?q=&limit=`                                                                    | Search the Strong's brief lexicons by gloss/transliteration/meaning (BM25)                                                                                                          |
| `GET /lexicon/{strongs}`                                                                    | Every lexicon entry for a Strong's number (dStrong, eStrong, or uStrong — a uStrong fans out to all entries unified under it, across both testaments)                               |
| `GET /notes?q=&limit=`                                                                      | Search personal commentary notes by title/body text (BM25)                                                                                                                          |
| `GET /notes/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}`                 | Personal notes anchored to a verse range                                                                                                                                             |
| `GET /note/{slug}`                                                                          | A single personal note by slug (its path under `notes/`, without `.md`)                                                                                                             |
| `GET /metadata/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}?translation=` | Everything known about a verse range in one call: overlapping pericopes, people, places, groups, events, TIPNR names, their lexicon entries (keyed by ustrong), NLP annotations, personal notes, the passage groups the book belongs to, and inherited `attributes` (author, date, ...) |
| `GET /metadata/pericope/{pericope_id}?translation=`                                         | The same combined payload, addressed by pericope id (the shape `/search` results come in)                                                                                           |
| `GET /reading/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}?translation=`  | A verse range laid out for reading: paragraphs, poetry line breaks/indentation, section headings, inline styling. NIV only for now — any other translation 404s                     |

`book` accepts either a number (`"1"`) or a name (`"Genesis"`) everywhere it
appears. `/people`, `/places`, `/events`, and `/reading`'s range params
(`chapter_start`/`verse_start`/`chapter_end`/`verse_end`) match the shape of the
`pericope` object returned by `/search` and `/pericopes` — after a search, the
client passes that same range straight through to look up who/where/what a
result is about. CORS is enabled for `http://localhost:5173` (the client dev
server).

Interactive Swagger docs are served at `/docs` (`/redoc` for the ReDoc
alternative) whenever the API is running.

## Testing

`tests/` holds a pytest suite covering every API endpoint, run via `task test`
(or `uv run pytest`). These are integration tests: they run the real FastAPI app
in-process against whatever data is currently ingested (see `tests/conftest.py`),
so the db must be up and ingested before running them — no mocking of
`theo.db.get_connection()`.

## Client

`client/` is a Vite + React + TypeScript app (Chakra UI for components, wouter
for routing) with:

- `/` — a landing page with a feature overview and headline stats.
- `/search` — query the `/search` endpoint (mode/limit/translation controls),
  results shown as pericope cards with their full verse text.
- `/verses` — fetch a chapter or verse range from `/verses`, laid out with the
  `/reading` formatting when available (NIV).
- `/events` and `/groups` — browse the theographic events and people groups.
- `/lexicon` — search the Strong's lexicons by English word (BM25 via
  `/lexicon?q=`) or by Strong's number (`/lexicon/{strongs}`); numbers like
  "h175" are auto-detected and normalized to the stored form ("H0175").

Passage cards on `/search` and `/verses` carry a collapsible "passage details"
panel that lazily makes a single `/metadata` call (by pericope id on the search
page, by verse range on the verses page) and shows everything known about the
passage: TIPNR names (click one for its name forms, prose article, and Strong's
lexicon entries), theographic people/places/groups/events, and the
subject–verb–object statements the NLP pipeline extracted.

It talks to the API directly at `http://localhost:8000` (override with
`VITE_API_BASE_URL`). Run it standalone with `task client`, or `pnpm install &&
pnpm dev` from inside `client/`.
