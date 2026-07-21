#!/bin/sh

#
# Assumes `uv` and `docker compose` are installed and set up on the host
#

set -e

# Start prod
# docker compose -f docker-compose.prod.yaml up -d --wait db

# Expose host for ingest commands
export POSTGRES_HOST=$(docker compose -f docker-compose.prod.yaml exec -T db hostname -i)

uv run ingest_verses.py data/bible/NIV/NIV_bible.json --translation NIV
uv run build_pericopes.py                    # writes data/pericopes.json
uv run ingest_pericopes.py data/pericopes.json
uv run embed_pericopes.py --translation NIV  # populates chunks_1024

uv run ingest_places.py                      # before ingest_people.py
uv run ingest_people.py                      # before ingest_people_groups.py
uv run ingest_people_groups.py               # before ingest_events.py
uv run ingest_events.py
uv run ingest_dictionary.py                  # after ingest_people.py / ingest_places.py

uv run ingest_reading.py                     # independent of the above

uv run ingest_step_names.py                  # independent of the above
uv run ingest_lexicon.py                     # independent of the above
uv run annotate_pericopes.py                 # spaCy+fastcoref pipeline; needs verses+pericopes; GPU recommended

# uncomment when we have validated that LLM is worth the $$$
# uv run llm_annotate_pericopes.py             # together.ai pipeline; needs TOGETHER_API_KEY in .env