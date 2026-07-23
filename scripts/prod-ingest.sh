#!/bin/sh

#
# Assumes `uv` and `docker compose` are installed and set up on the host
#

set -e

# Start prod
# docker compose -f docker-compose.prod.yaml up -d --wait db

# Expose host for ingest commands
export POSTGRES_HOST=$(docker compose -f docker-compose.prod.yaml exec -T db hostname -i)

uv run -m scripts.ingest_verses data/bible/NIV/NIV_bible.json --translation NIV
uv run -m scripts.build_pericopes                    # writes data/pericopes.json
uv run -m scripts.ingest_pericopes data/pericopes.json
uv run -m scripts.embed_pericopes --translation NIV  # populates chunks_1024

uv run -m scripts.ingest_places                      # before ingest_people.py
uv run -m scripts.ingest_people                      # before ingest_people_groups.py
uv run -m scripts.ingest_people_groups               # before ingest_events.py
uv run -m scripts.ingest_events
uv run -m scripts.ingest_dictionary                  # after ingest_people.py / ingest_places.py

uv run -m scripts.ingest_reading                     # independent of the above

uv run -m scripts.ingest_step_names                  # independent of the above
uv run -m scripts.ingest_lexicon                     # independent of the above
uv run -m scripts.annotate_pericopes                 # spaCy+fastcoref pipeline; needs verses+pericopes; GPU recommended

# uncomment when we have validated that LLM is worth the $$$
# uv run -m scripts.llm_annotate_pericopes             # together.ai pipeline; needs TOGETHER_API_KEY in .env
