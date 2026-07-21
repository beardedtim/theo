-- Loaded by the ParadeDB container on first boot (see docker-compose.yml).
-- Runs after the image's own bootstrap script, which already enables the
-- `vector` and `pg_search` extensions on this database.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;

-- ParadeDB 0.24.3's DataFusion aggregate scan returns wrong results for SQL
-- aggregates over joins with non-equi conditions (verified here: a count(*)
-- over the verses/pericopes range join returned 2,073,477 instead of the
-- true 31,101 -- the non-equi join quals were silently dropped). The app
-- only needs ParadeDB for the @@@ BM25 operator, so turn the aggregate scan
-- off instance-wide until an upstream fix is verified.
ALTER SYSTEM SET paradedb.enable_aggregate_custom_scan = off;
SELECT pg_reload_conf();

-- Theo Data Model
--
-- Verse: Source of truth for what the text says in some unit of work
--          it has columns for Verse Number, Chapter Number, Book. 
--
-- Pericope: Source for what groupings go together. It says what verse
--              id to start with and what verse ID to end with, along
--              with any description/title/etc
--
-- Chunk: Some semantic chunk of Pericopes, a single Pericope, or parts
--          of a pericope. This depends on the Embedding system we use,
--          the Verse and Pericope are part of our underlying data model


-- Verse. The root of all future data
--
CREATE TABLE IF NOT EXISTS verses (
    id UUID NOT NULL DEFAULT uuidv7(),
    raw_text TEXT NOT NULL,
    verse_num INT NOT NULL,
    chapt_num INT NOT NULL,
    book INT NOT NULL,
    translation TEXT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT unique_verse UNIQUE (translation, book, chapt_num, verse_num)
);

-- Allow us to look up the Book Chapter:Verse _across_ translations
CREATE INDEX verses_book_chapt_verse_idx ON verses (book, chapt_num, verse_num);

-- Create a single BM25 index that handles full-text search AND filtering
CREATE INDEX verses_search_idx ON verses USING bm25 (
    id,
    raw_text,
    translation,
    book,
    chapt_num
) WITH (key_field = 'id');


-- Pericope. The grouping of verses and the root of chunks
--
CREATE TABLE IF NOT EXISTS pericopes (
    id UUID NOT NULL DEFAULT uuidv7(),
    raw_text TEXT NOT NULL,         -- The title or description of the pericope
    book INT NOT NULL,              -- Assuming pericopes do not span across multiple books
    chapter_start INT NOT NULL,
    verse_start INT NOT NULL,
    chapter_end INT NOT NULL,
    verse_end INT NOT NULL,
    PRIMARY KEY (id),

    -- Ensure the end boundary mathematically follows the start boundary
    CONSTRAINT valid_pericope_range CHECK (
        (chapter_end > chapter_start) OR
        (chapter_end = chapter_start AND verse_end >= verse_start)
    ),
    CONSTRAINT unique_pericope_range UNIQUE (book, chapter_start, verse_start, chapter_end, verse_end)
);

CREATE INDEX pericopes_location_idx ON pericopes(book, chapter_start, verse_start);

CREATE INDEX pericopes_search_idx ON pericopes USING bm25 (
    id,
    raw_text,
    book
) WITH (key_field = 'id');

-- Chunks for 1536-dimension embedding models (e.g., OpenAI text-embedding-3-small)
CREATE TABLE IF NOT EXISTS chunks_1536 (
    id UUID NOT NULL DEFAULT uuidv7(),
    pericope_id UUID NOT NULL,
    embedding_model TEXT NOT NULL,     
    chunk_seq INT NOT NULL,            
    raw_text TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}'::jsonb, 
    PRIMARY KEY (id),
    
    -- Constraint names must include the dimension to avoid schema collisions
    CONSTRAINT fk_chunks_1536_pericope FOREIGN KEY (pericope_id) REFERENCES pericopes(id) ON DELETE CASCADE,
    CONSTRAINT chunks_1536_unique_model UNIQUE (pericope_id, embedding_model, chunk_seq)
);

-- Index names must also be unique across the schema
CREATE INDEX chunks_1536_model_idx ON chunks_1536(embedding_model);
CREATE INDEX chunks_1536_pericope_id_idx ON chunks_1536(pericope_id);
CREATE INDEX chunks_1536_embedding_idx ON chunks_1536 USING hnsw (embedding vector_cosine_ops);

-- The ParadeDB BM25 Index (For Keyword/Hybrid search)
-- Indexing the model allows fast filtering to ensure you only search within one model's vectors
CREATE INDEX chunks_search_idx ON chunks_1536 USING bm25 (
    id,
    pericope_id,
    raw_text,
    embedding_model
) WITH (key_field = 'id');

-- Chunks for 1024-dimension embedding models (e.g., BAAI/bge-large-en-v1.5)
CREATE TABLE IF NOT EXISTS chunks_1024 (
    id UUID NOT NULL DEFAULT uuidv7(),
    pericope_id UUID NOT NULL,
    embedding_model TEXT NOT NULL,
    chunk_seq INT NOT NULL,
    raw_text TEXT NOT NULL,
    embedding vector(1024),
    metadata JSONB DEFAULT '{}'::jsonb,
    PRIMARY KEY (id),

    -- Constraint names must include the dimension to avoid schema collisions
    CONSTRAINT fk_chunks_1024_pericope FOREIGN KEY (pericope_id) REFERENCES pericopes(id) ON DELETE CASCADE,
    CONSTRAINT chunks_1024_unique_model UNIQUE (pericope_id, embedding_model, chunk_seq)
);

-- Index names must also be unique across the schema
CREATE INDEX chunks_1024_model_idx ON chunks_1024(embedding_model);
CREATE INDEX chunks_1024_pericope_id_idx ON chunks_1024(pericope_id);
CREATE INDEX chunks_1024_embedding_idx ON chunks_1024 USING hnsw (embedding vector_cosine_ops);

CREATE INDEX chunks_1024_search_idx ON chunks_1024 USING bm25 (
    id,
    pericope_id,
    raw_text,
    embedding_model
) WITH (key_field = 'id');


-- Theographic Knowledge-Graph Data (https://theographic.bible)
--
-- Person / Place: entities from the Theographic Bible Metadata dataset.
-- Like Pericope, these are translation-independent facts about a passage,
-- so they reference (book, chapt_num, verse_num) coordinates directly via
-- the verse_* junction tables below, rather than FK'ing to a specific
-- translation's verses.id row. Each table also carries a `theographic_id`
-- column -- the source's opaque, stable Airtable record id -- as the
-- natural key ingestion is idempotent against, distinct from Theo's own
-- generated `id`.

-- Place. Geographic locations referenced by people and verses.
--
CREATE TABLE IF NOT EXISTS places (
    id UUID NOT NULL DEFAULT uuidv7(),
    theographic_id TEXT NOT NULL,        -- Airtable record id, e.g. "recirTpwii9yXJ9JM"
    place_lookup TEXT NOT NULL,          -- stable slug, e.g. "jerusalem_636"
    place_num INT NOT NULL,              -- theographic placeID
    kjv_name TEXT NOT NULL,
    display_title TEXT NOT NULL,
    feature_type TEXT,                   -- e.g. "City", "Water", "Mountain"
    feature_sub_type TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    dictionary_text TEXT,                -- inlined Easton's dictionary snippet, if any
    PRIMARY KEY (id),
    CONSTRAINT unique_places_theographic_id UNIQUE (theographic_id)
);

CREATE INDEX places_place_lookup_idx ON places(place_lookup);

CREATE INDEX places_search_idx ON places USING bm25 (
    id,
    kjv_name,
    display_title,
    feature_type,
    dictionary_text
) WITH (key_field = 'id');


-- Person. Individuals referenced by verses.
--
CREATE TABLE IF NOT EXISTS people (
    id UUID NOT NULL DEFAULT uuidv7(),
    theographic_id TEXT NOT NULL,        -- Airtable record id
    person_lookup TEXT NOT NULL,         -- stable slug, e.g. "david_994"
    person_num INT NOT NULL,             -- theographic personID
    name TEXT NOT NULL,
    display_title TEXT NOT NULL,         -- disambiguated display form
    gender TEXT,
    is_proper_name BOOLEAN,
    also_called TEXT,
    dictionary_text TEXT,                -- inlined Easton's dictionary snippet, if any
    birth_year INT,                      -- ISO astronomical year numbering; NULL if unknown
    death_year INT,

    -- Verified 0-or-1 in every theographic record, so these are plain FK
    -- columns rather than a relationship table. `children` is deliberately
    -- NOT stored -- it's derivable via mother_id/father_id and would
    -- otherwise be a second, occasionally-inconsistent source of the same fact.
    mother_id UUID,
    father_id UUID,
    birth_place_id UUID,
    death_place_id UUID,

    PRIMARY KEY (id),
    CONSTRAINT unique_people_theographic_id UNIQUE (theographic_id),
    CONSTRAINT fk_people_mother FOREIGN KEY (mother_id) REFERENCES people(id) ON DELETE SET NULL,
    CONSTRAINT fk_people_father FOREIGN KEY (father_id) REFERENCES people(id) ON DELETE SET NULL,
    CONSTRAINT fk_people_birth_place FOREIGN KEY (birth_place_id) REFERENCES places(id) ON DELETE SET NULL,
    CONSTRAINT fk_people_death_place FOREIGN KEY (death_place_id) REFERENCES places(id) ON DELETE SET NULL
);

CREATE INDEX people_person_lookup_idx ON people(person_lookup);
CREATE INDEX people_mother_id_idx ON people(mother_id);   -- powers "children of X" queries
CREATE INDEX people_father_id_idx ON people(father_id);

CREATE INDEX people_search_idx ON people USING bm25 (
    id,
    name,
    display_title,
    also_called,
    dictionary_text
) WITH (key_field = 'id');


-- Sibling/half-sibling/partner edges -- genuinely multi-valued and
-- symmetric in the source (verified 0 asymmetric pairs across 4,660
-- sibling edges), so one generic table instead of three near-identical
-- junction tables. `children` is intentionally absent -- derive it from
-- people.mother_id/father_id instead.
CREATE TABLE IF NOT EXISTS person_relationships (
    id UUID NOT NULL DEFAULT uuidv7(),
    person_id UUID NOT NULL,
    related_person_id UUID NOT NULL,
    relation_type TEXT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_person_relationships_person FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
    CONSTRAINT fk_person_relationships_related FOREIGN KEY (related_person_id) REFERENCES people(id) ON DELETE CASCADE,
    CONSTRAINT unique_person_relationships UNIQUE (person_id, related_person_id, relation_type),
    CONSTRAINT person_relationships_no_self_reference CHECK (person_id <> related_person_id),
    CONSTRAINT person_relationships_valid_type CHECK (
        relation_type IN ('sibling', 'half_sibling_maternal', 'half_sibling_paternal', 'partner')
    )
);
CREATE INDEX person_relationships_person_idx ON person_relationships(person_id);
CREATE INDEX person_relationships_related_idx ON person_relationships(related_person_id);


-- Verse-coordinate junctions. Same pattern as `pericopes`: these facts are
-- translation-independent, so they reference (book, chapt_num, verse_num)
-- coordinates directly rather than a specific translation's verses.id row.
CREATE TABLE IF NOT EXISTS verse_people (
    id UUID NOT NULL DEFAULT uuidv7(),
    person_id UUID NOT NULL,
    book INT NOT NULL,
    chapt_num INT NOT NULL,
    verse_num INT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_verse_people_person FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
    CONSTRAINT unique_verse_people UNIQUE (person_id, book, chapt_num, verse_num)
);
CREATE INDEX verse_people_location_idx ON verse_people(book, chapt_num, verse_num);
CREATE INDEX verse_people_person_idx ON verse_people(person_id);

CREATE TABLE IF NOT EXISTS verse_places (
    id UUID NOT NULL DEFAULT uuidv7(),
    place_id UUID NOT NULL,
    book INT NOT NULL,
    chapt_num INT NOT NULL,
    verse_num INT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_verse_places_place FOREIGN KEY (place_id) REFERENCES places(id) ON DELETE CASCADE,
    CONSTRAINT unique_verse_places UNIQUE (place_id, book, chapt_num, verse_num)
);
CREATE INDEX verse_places_location_idx ON verse_places(book, chapt_num, verse_num);
CREATE INDEX verse_places_place_idx ON verse_places(place_id);

-- PeopleGroup. Named collections of people (tribes, apostles, genealogies...).
CREATE TABLE IF NOT EXISTS people_groups (
    id UUID NOT NULL DEFAULT uuidv7(),
    theographic_id TEXT NOT NULL,
    group_name TEXT NOT NULL,
    parent_group_id UUID,                -- partOf; verified 0-or-1 in all 23 groups
    PRIMARY KEY (id),
    CONSTRAINT unique_people_groups_theographic_id UNIQUE (theographic_id),
    CONSTRAINT fk_people_groups_parent FOREIGN KEY (parent_group_id) REFERENCES people_groups(id) ON DELETE SET NULL
);
CREATE INDEX people_groups_parent_id_idx ON people_groups(parent_group_id);
CREATE INDEX people_groups_search_idx ON people_groups USING bm25 (id, group_name) WITH (key_field = 'id');

CREATE TABLE IF NOT EXISTS people_group_members (
    id UUID NOT NULL DEFAULT uuidv7(),
    group_id UUID NOT NULL,
    person_id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_people_group_members_group FOREIGN KEY (group_id) REFERENCES people_groups(id) ON DELETE CASCADE,
    CONSTRAINT fk_people_group_members_person FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
    CONSTRAINT unique_people_group_members UNIQUE (group_id, person_id)
);
CREATE INDEX people_group_members_group_idx ON people_group_members(group_id);
CREATE INDEX people_group_members_person_idx ON people_group_members(person_id);

CREATE TABLE IF NOT EXISTS people_group_verses (
    id UUID NOT NULL DEFAULT uuidv7(),
    group_id UUID NOT NULL,
    book INT NOT NULL,
    chapt_num INT NOT NULL,
    verse_num INT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_people_group_verses_group FOREIGN KEY (group_id) REFERENCES people_groups(id) ON DELETE CASCADE,
    CONSTRAINT unique_people_group_verses UNIQUE (group_id, book, chapt_num, verse_num)
);
CREATE INDEX people_group_verses_location_idx ON people_group_verses(book, chapt_num, verse_num);
CREATE INDEX people_group_verses_group_idx ON people_group_verses(group_id);


-- Event. A biographical/historical event, e.g. "Exodus from Egypt".
CREATE TABLE IF NOT EXISTS events (
    id UUID NOT NULL DEFAULT uuidv7(),
    theographic_id TEXT NOT NULL,
    event_num INT NOT NULL,              -- theographic eventID
    title TEXT NOT NULL,
    start_date TEXT,                     -- signed year ("-4003") or "YYYY-MM-DD"; format
                                          -- varies by era, kept as source text rather than DATE
    duration TEXT,                       -- theographic shorthand, e.g. "7D", "22Y", "19M"
    sort_key DOUBLE PRECISION,           -- precomputed chronological sort, uniform across
                                          -- the mixed start_date formats above
    predecessor_id UUID,                 -- verified 0-or-1 in all 450 events
    PRIMARY KEY (id),
    CONSTRAINT unique_events_theographic_id UNIQUE (theographic_id),
    CONSTRAINT fk_events_predecessor FOREIGN KEY (predecessor_id) REFERENCES events(id) ON DELETE SET NULL
);
CREATE INDEX events_sort_key_idx ON events(sort_key);
CREATE INDEX events_predecessor_id_idx ON events(predecessor_id);
CREATE INDEX events_search_idx ON events USING bm25 (id, title) WITH (key_field = 'id');

-- partOf: not always 0-or-1 (1 of 450 events has two parents) -> junction, not FK.
CREATE TABLE IF NOT EXISTS event_parts (
    id UUID NOT NULL DEFAULT uuidv7(),
    event_id UUID NOT NULL,
    parent_event_id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_event_parts_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_event_parts_parent FOREIGN KEY (parent_event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT unique_event_parts UNIQUE (event_id, parent_event_id),
    CONSTRAINT event_parts_no_self_reference CHECK (event_id <> parent_event_id)
);
CREATE INDEX event_parts_event_idx ON event_parts(event_id);
CREATE INDEX event_parts_parent_idx ON event_parts(parent_event_id);

CREATE TABLE IF NOT EXISTS event_people (
    id UUID NOT NULL DEFAULT uuidv7(),
    event_id UUID NOT NULL,
    person_id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_event_people_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_event_people_person FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
    CONSTRAINT unique_event_people UNIQUE (event_id, person_id)
);
CREATE INDEX event_people_event_idx ON event_people(event_id);
CREATE INDEX event_people_person_idx ON event_people(person_id);

CREATE TABLE IF NOT EXISTS event_places (
    id UUID NOT NULL DEFAULT uuidv7(),
    event_id UUID NOT NULL,
    place_id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_event_places_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_event_places_place FOREIGN KEY (place_id) REFERENCES places(id) ON DELETE CASCADE,
    CONSTRAINT unique_event_places UNIQUE (event_id, place_id)
);
CREATE INDEX event_places_event_idx ON event_places(event_id);
CREATE INDEX event_places_place_idx ON event_places(place_id);

CREATE TABLE IF NOT EXISTS event_groups (
    id UUID NOT NULL DEFAULT uuidv7(),
    event_id UUID NOT NULL,
    group_id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_event_groups_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT fk_event_groups_group FOREIGN KEY (group_id) REFERENCES people_groups(id) ON DELETE CASCADE,
    CONSTRAINT unique_event_groups UNIQUE (event_id, group_id)
);
CREATE INDEX event_groups_event_idx ON event_groups(event_id);
CREATE INDEX event_groups_group_idx ON event_groups(group_id);

CREATE TABLE IF NOT EXISTS event_verses (
    id UUID NOT NULL DEFAULT uuidv7(),
    event_id UUID NOT NULL,
    book INT NOT NULL,
    chapt_num INT NOT NULL,
    verse_num INT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_event_verses_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    CONSTRAINT unique_event_verses UNIQUE (event_id, book, chapt_num, verse_num)
);
CREATE INDEX event_verses_location_idx ON event_verses(book, chapt_num, verse_num);
CREATE INDEX event_verses_event_idx ON event_verses(event_id);


-- Easton's Bible Dictionary (1897), theographic's cross-linked edition.
CREATE TABLE IF NOT EXISTS dictionary_entries (
    id UUID NOT NULL DEFAULT uuidv7(),
    theographic_id TEXT NOT NULL,
    term TEXT NOT NULL,                  -- termLabel, e.g. "Abda"
    entry_text TEXT,                     -- dictText; ~2% of entries have none
    entry_order INT NOT NULL,            -- theographic's `index` -- stable print/reading order
    PRIMARY KEY (id),
    CONSTRAINT unique_dictionary_entries_theographic_id UNIQUE (theographic_id)
);
CREATE INDEX dictionary_entries_order_idx ON dictionary_entries(entry_order);
CREATE INDEX dictionary_entries_search_idx ON dictionary_entries USING bm25 (id, term, entry_text) WITH (key_field = 'id');

-- An entry can match more than one same-named person/place, and 22 entries
-- match both a person AND a place -> junction tables, not FK columns.
CREATE TABLE IF NOT EXISTS dictionary_entry_people (
    id UUID NOT NULL DEFAULT uuidv7(),
    dictionary_entry_id UUID NOT NULL,
    person_id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_dictionary_entry_people_entry FOREIGN KEY (dictionary_entry_id) REFERENCES dictionary_entries(id) ON DELETE CASCADE,
    CONSTRAINT fk_dictionary_entry_people_person FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
    CONSTRAINT unique_dictionary_entry_people UNIQUE (dictionary_entry_id, person_id)
);
CREATE INDEX dictionary_entry_people_entry_idx ON dictionary_entry_people(dictionary_entry_id);
CREATE INDEX dictionary_entry_people_person_idx ON dictionary_entry_people(person_id);

CREATE TABLE IF NOT EXISTS dictionary_entry_places (
    id UUID NOT NULL DEFAULT uuidv7(),
    dictionary_entry_id UUID NOT NULL,
    place_id UUID NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_dictionary_entry_places_entry FOREIGN KEY (dictionary_entry_id) REFERENCES dictionary_entries(id) ON DELETE CASCADE,
    CONSTRAINT fk_dictionary_entry_places_place FOREIGN KEY (place_id) REFERENCES places(id) ON DELETE CASCADE,
    CONSTRAINT unique_dictionary_entry_places UNIQUE (dictionary_entry_id, place_id)
);
CREATE INDEX dictionary_entry_places_entry_idx ON dictionary_entry_places(dictionary_entry_id);
CREATE INDEX dictionary_entry_places_place_idx ON dictionary_entry_places(place_id);


-- Reading-formatted text (paragraph/poetry layout + inline styling),
-- sourced from jburson/bible-data's per-word markup format
-- (data/info/data/<translation>/<translation>.json -- see build_pericopes.py
-- for the existing precedent reading this source). Deliberately separate
-- from `verses`/`pericopes`, which stay the flat/raw source of truth for
-- search and the theographic verse-range joins -- this is purely a "how do
-- we lay this out for reading" concern. NIV only for now.
CREATE TABLE IF NOT EXISTS reading_verses (
    id UUID NOT NULL DEFAULT uuidv7(),
    translation TEXT NOT NULL,
    book INT NOT NULL,
    chapt_num INT NOT NULL,
    verse_num INT NOT NULL,
    tokens JSONB NOT NULL,   -- [{"word": "In", "codes": "p"}, {"word": "the"}, ...]
                              -- raw parsed tokens, un-interpreted -- see theo/reading.py
    PRIMARY KEY (id),
    CONSTRAINT unique_reading_verses UNIQUE (translation, book, chapt_num, verse_num)
);
CREATE INDEX IF NOT EXISTS reading_verses_lookup_idx ON reading_verses (translation, book, chapt_num, verse_num);

CREATE TABLE IF NOT EXISTS reading_headings (
    id UUID NOT NULL DEFAULT uuidv7(),
    translation TEXT NOT NULL,
    book INT NOT NULL,
    chapt_num INT NOT NULL,
    anchor_verse_num INT NOT NULL,   -- verse this heading precedes; 0 = before the chapter's first verse
    order_num INT NOT NULL,          -- source `o`; tiebreaks multiple headings anchored to the same verse
    level REAL NOT NULL,             -- source `h`: 1/2/2.5/3/4
    heading_text TEXT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT unique_reading_headings UNIQUE (translation, book, chapt_num, order_num)
);
CREATE INDEX IF NOT EXISTS reading_headings_lookup_idx ON reading_headings (translation, book, chapt_num, anchor_verse_num);


-- STEPBible TIPNR proper nouns (data/step-bible/Proper Nouns/..., CC BY).
--
-- Every proper noun in the Bible (persons, places, months, deities, ...),
-- one row per distinct individual/location, with a Strong's-derived id
-- (uStrong), every name form it appears under (step_name_forms), and an
-- exhaustive per-verse occurrence list (step_name_verses) derived from the
-- Hebrew/Greek tagging -- i.e. ground-truth entity links per verse, no NER
-- guessing. Family/founder relation fields are kept as raw display text;
-- theographic's people/person_relationships stays the relationship graph.
CREATE TABLE IF NOT EXISTS step_names (
    id UUID NOT NULL DEFAULT uuidv7(),
    tipnr_key TEXT NOT NULL,        -- full header key "Aaron@Exo.4.14-Heb=H0175"; the
                                     -- record's guaranteed-unique natural identity
    ustrong TEXT NOT NULL,          -- unified Strong's number, e.g. "H0175"
    name TEXT NOT NULL,             -- display name, the part before "@"
    category TEXT NOT NULL,         -- person | place | other
    entity_type TEXT,               -- Male, Female, Place, Supernatural, Time, Musical, ...
    description TEXT,               -- e.g. "High Priest living at the time of Egypt and Wilderness"
    -- person fields (raw TIPNR text, unresolved)
    parents TEXT,
    siblings TEXT,
    partners TEXT,
    offspring TEXT,
    tribe TEXT,
    -- place fields
    openbible_name TEXT,
    founder TEXT,
    inhabitants TEXT,
    geo_area TEXT,
    latitude DOUBLE PRECISION,      -- parsed from the record's Google-Maps URL
    longitude DOUBLE PRECISION,
    -- prose
    summary_html TEXT,              -- "#Summary" field; contains <ref>/<strong> markup
    briefest TEXT,
    brief TEXT,
    short_desc TEXT,
    article_html TEXT,              -- up to 6 paragraphs, <BR>-separated
    PRIMARY KEY (id),
    CONSTRAINT unique_step_names_tipnr_key UNIQUE (tipnr_key),
    CONSTRAINT step_names_valid_category CHECK (category IN ('person', 'place', 'other'))
);
CREATE INDEX IF NOT EXISTS step_names_ustrong_idx ON step_names(ustrong);
CREATE INDEX IF NOT EXISTS step_names_name_idx ON step_names(name);

CREATE INDEX IF NOT EXISTS step_names_search_idx ON step_names USING bm25 (
    id,
    name,
    description,
    short_desc,
    article_html
) WITH (key_field = 'id');

-- One row per name form of a step_name: alternate spellings, Greek forms,
-- combined names, etc., each with its own disambiguated Strong's number and
-- original-language script.
CREATE TABLE IF NOT EXISTS step_name_forms (
    id UUID NOT NULL DEFAULT uuidv7(),
    step_name_id UUID NOT NULL,
    form_seq INT NOT NULL,          -- order within the source record
    significance TEXT NOT NULL,     -- Named, Greek, Spelled, Mentioned, Group, ...
    unique_name TEXT,               -- "AltName|UnifiedName@ref" form
    strongs_raw TEXT,               -- full source field, e.g. "H0175«H0175=אַהֲרֹן"
                                     -- (may be compound, joined with "+")
    dstrong TEXT,                   -- first disambiguated Strong's, e.g. "H5658I"
    estrong TEXT,                   -- first electronic Strong's, e.g. "H5658"
    original TEXT,                  -- Hebrew/Greek script of the first segment
    translations TEXT,              -- e.g. "Ebron =ESV; Abdon =NIV; Hebron =KJV"
    PRIMARY KEY (id),
    CONSTRAINT fk_step_name_forms_name FOREIGN KEY (step_name_id) REFERENCES step_names(id) ON DELETE CASCADE,
    CONSTRAINT unique_step_name_forms UNIQUE (step_name_id, form_seq)
);
CREATE INDEX IF NOT EXISTS step_name_forms_name_idx ON step_name_forms(step_name_id);
CREATE INDEX IF NOT EXISTS step_name_forms_dstrong_idx ON step_name_forms(dstrong);

-- Exhaustive per-verse occurrences of each name form. Translation-independent
-- (derived from the original-language tagging), so coordinates are referenced
-- directly like verse_people/verse_places. Alt-Tag/Variant sub-records
-- legitimately repeat the same refs under different tagging, so entity-level
-- lookups should SELECT DISTINCT across forms.
CREATE TABLE IF NOT EXISTS step_name_verses (
    id UUID NOT NULL DEFAULT uuidv7(),
    step_name_id UUID NOT NULL,
    form_id UUID NOT NULL,
    book INT NOT NULL,
    chapt_num INT NOT NULL,
    verse_num INT NOT NULL,
    occurrence TEXT NOT NULL DEFAULT '',  -- "a"/"b" suffix when a form appears
                                           -- more than once in a verse; '' otherwise
                                           -- (non-null so the unique constraint dedupes)
    PRIMARY KEY (id),
    CONSTRAINT fk_step_name_verses_name FOREIGN KEY (step_name_id) REFERENCES step_names(id) ON DELETE CASCADE,
    CONSTRAINT fk_step_name_verses_form FOREIGN KEY (form_id) REFERENCES step_name_forms(id) ON DELETE CASCADE,
    CONSTRAINT unique_step_name_verses UNIQUE (form_id, book, chapt_num, verse_num, occurrence)
);
CREATE INDEX IF NOT EXISTS step_name_verses_location_idx ON step_name_verses(book, chapt_num, verse_num);
CREATE INDEX IF NOT EXISTS step_name_verses_name_idx ON step_name_verses(step_name_id);


-- NLP annotations, one row per (pericope, translation, pipeline). The
-- pericope is the processing unit because coref and SVO need multi-verse
-- context ("Jesus wept" alone has no antecedents). `pipeline` versions the
-- producing code+models so different producers (the local spaCy/fastcoref
-- pipeline, an LLM via together.ai) and reprocesses under a new version can
-- coexist with (and be compared against) each other.
CREATE TABLE IF NOT EXISTS pericope_annotations (
    id UUID NOT NULL DEFAULT uuidv7(),
    pericope_id UUID NOT NULL,
    translation TEXT NOT NULL,
    pipeline TEXT NOT NULL,          -- e.g. "en_core_web_trf+fastcoref/v1", "together:deepseek-ai/DeepSeek-V4-Pro/v1"
    resolved_text TEXT,              -- coref-resolved pericope text
    entities JSONB,                  -- [{"text","label","ustrong","start","end"}, ...]
    svo JSONB,                       -- [["subject","verb-lemma","object"], ...]
    extras JSONB,                    -- LLM-only enrichments: {"summary","genre","themes",
                                     -- "keywords","tone","speech_acts"}; NULL for spaCy rows
    PRIMARY KEY (id),
    CONSTRAINT fk_pericope_annotations_pericope FOREIGN KEY (pericope_id) REFERENCES pericopes(id) ON DELETE CASCADE,
    CONSTRAINT unique_pericope_annotations UNIQUE (pericope_id, translation, pipeline)
);
CREATE INDEX IF NOT EXISTS pericope_annotations_pericope_idx ON pericope_annotations(pericope_id);

-- STEPBible's TBESH/TBESG brief lexicons: one row per disambiguated Strong's
-- number (dStrong -- unique across both testaments), giving the original-
-- language lemma, transliteration, morphology, a one-word gloss, and a brief
-- meaning. `ustrong` links entries to `step_names.ustrong` and to the
-- gazetteer ids stored in `pericope_annotations` entities. Meanings are from
-- Abridged BDB (Hebrew, © Online Bible -- guidance only) and Abbott-Smith /
-- Middle Liddell (Greek).
CREATE TABLE IF NOT EXISTS step_lexicon (
    id UUID NOT NULL DEFAULT uuidv7(),
    dstrong TEXT NOT NULL,          -- disambiguated Strong's, e.g. "H0175", "G2264H"
    estrong TEXT NOT NULL,          -- extended Strong's (repeats across dStrong sub-entries)
    ustrong TEXT NOT NULL,          -- unified Strong's this entry resolves to
    ustrong_raw TEXT,               -- source uStrong field when it carried more than the
                                     -- code (e.g. "H9007 (H9007+H9005)" compounds); else NULL
    relation TEXT,                  -- how dstrong relates to ustrong: "a Name of",
                                     -- "in Aramaic of", "the Greek of", ...; NULL for plain "="
    language TEXT NOT NULL,
    original TEXT,                  -- Hebrew/Greek script lemma
    transliteration TEXT,
    morph TEXT,                     -- e.g. "H:N-M", "N:N-M-P", "G:V"
    gloss TEXT,                     -- one-word meaning
    meaning_html TEXT,              -- brief lexicon entry; contains <br>/<i>/<ref> markup
    PRIMARY KEY (id),
    CONSTRAINT unique_step_lexicon_dstrong UNIQUE (dstrong),
    CONSTRAINT step_lexicon_valid_language CHECK (language IN ('hebrew', 'greek'))
);
CREATE INDEX IF NOT EXISTS step_lexicon_estrong_idx ON step_lexicon(estrong);
CREATE INDEX IF NOT EXISTS step_lexicon_ustrong_idx ON step_lexicon(ustrong);

CREATE INDEX IF NOT EXISTS step_lexicon_search_idx ON step_lexicon USING bm25 (
    id,
    gloss,
    transliteration,
    meaning_html
) WITH (key_field = 'id');
