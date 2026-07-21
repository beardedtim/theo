"""LLM-based NLP enrichment via together.ai chat completions.

The LLM analogue of theo.parse: given a passage of text it produces the same
core outputs (entities, SVO triples, coref-resolved text) plus enrichments a
dependency parse can't give -- themes, keywords, a one-sentence summary,
tone, genre, and speech acts (who speaks to whom). Results are shaped to
drop straight into `pericope_annotations`: entities/svo/resolved_text use
the exact JSON shapes the spaCy pipeline stores (entity `start`/`end`/
`ustrong` are None -- an LLM can't give reliable character offsets), and the
LLM-only fields are bundled into an `extras` dict for the JSONB column of
the same name.

Pure API access -- no database. theo.llm_annotations handles storage.
Requires TOGETHER_API_KEY in the environment (or .env).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Literal

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

logger = logging.getLogger(__name__)

API_URL = "https://api.together.xyz/v1/chat/completions"
# Must be a SERVERLESS model on together.ai: dedicated-endpoint-only models
# (e.g. deepseek-ai/DeepSeek-V3.1) 400 with "model_not_available" even though
# they appear in the /v1/models listing.
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4-Pro"

# Storage rows are keyed on this (see theo.annotations): the model is part of
# the identity, and the trailing version covers prompt/schema changes, so a
# reprocess under a reworked prompt coexists with old rows.
def pipeline_id(model: str = DEFAULT_MODEL) -> str:
    return f"together:{model}/v1"


# --- Response schema (also sent to the API for constrained JSON output) ------

# spaCy NER labels the client already renders, plus DEITY: divine references
# are the most common entity in this corpus and folding them into PERSON
# loses the distinction the TIPNR gazetteer works hard to keep.
EntityLabel = Literal[
    "PERSON", "DEITY", "NORP", "LOC", "GPE", "EVENT",
    "DATE", "TIME", "LANGUAGE", "WORK_OF_ART", "OBJECT", "MISC",
]

Genre = Literal[
    "narrative", "poetry", "law", "prophecy", "wisdom", "parable",
    "discourse", "epistle", "apocalyptic", "genealogy", "other",
]


class LlmEntity(BaseModel):
    text: str = Field(description="The entity exactly as written in the passage")
    label: EntityLabel


class SvoTriple(BaseModel):
    subject: str
    verb: str = Field(description="The verb as a lemma, e.g. 'create', not 'created'")
    object: str


class SpeechAct(BaseModel):
    speaker: str
    addressee: str
    act: str = Field(description="Short label: command, promise, blessing, question, rebuke, prayer, ...")


class LlmAnnotation(BaseModel):
    """What the model must return for one passage.

    The max_length caps become maxItems in the JSON schema sent to the API.
    They are deliberately generous -- their job is not to limit legitimate
    output but to hard-stop degenerate repetition loops: on liturgically
    repetitive text (every verse of Psalm 119 is a petition to the Lord),
    constrained decoding otherwise emits the same identical list entry until
    it hits the response token cap."""
    resolved_text: str = Field(
        description="The passage with pronouns/coreferences replaced by their antecedents"
    )
    entities: list[LlmEntity] = Field(max_length=80)
    svo: list[SvoTriple] = Field(
        description="Subject-verb-object statements, with coreferences resolved",
        max_length=100,
    )
    themes: list[str] = Field(
        description="Topical tags, e.g. 'covenant', 'forgiveness'", max_length=12
    )
    keywords: list[str] = Field(
        description="Salient words/phrases from the passage", max_length=20
    )
    summary: str = Field(description="One sentence summarizing the passage")
    tone: list[str] = Field(
        description="Emotional tone descriptors, e.g. 'solemn', 'joyful'", max_length=8
    )
    genre: Genre
    speech_acts: list[SpeechAct] = Field(max_length=25)


# --- Prompting ---------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a biblical-studies NLP annotator. Given a Bible passage (a pericope), \
produce structured metadata for a search engine. Respond with ONLY a JSON \
object matching the schema you are given -- no prose, no markdown fences.

Guidelines:
- resolved_text: rewrite the passage replacing pronouns and other coreferences \
with their antecedents ("He stayed there" -> "Moses stayed on the mountain"). \
Keep everything else word-for-word.
- entities: every named entity in the passage. Use DEITY for God, the LORD, \
Jesus, the Spirit; PERSON for humans; NORP for tribes/nations/peoples as \
groups; LOC/GPE for places; OBJECT for significant named artifacts (the ark, \
the temple). Deduplicate: one entry per distinct entity, using its most \
complete written form.
- svo: the key factual statements as (subject, verb-lemma, object) triples, \
subjects and objects coref-resolved to names where possible. Cover the \
passage's main actions; skip auxiliary/copular trivia.
- themes: 3-8 topical tags a reader might search by (e.g. covenant, exile, \
resurrection, faith under trial).
- keywords: the most salient words and short phrases actually in the passage.
- summary: exactly one sentence.
- tone / genre: overall register of the passage.
- speech_acts: one entry per distinct (speaker, addressee, act) combination \
of direct speech, labeling the kind of act (command, promise, question, \
blessing, ...). Empty list if there is no direct speech.
- Every list must be free of duplicates: never emit the same entity, triple, \
tag, or speech act twice. In repetitive passages (litanies, refrains, \
acrostics) each distinct item appears ONCE no matter how often the text \
repeats it.\
"""


def _user_prompt(reference: str, title: str, text: str) -> str:
    return f"Passage: {reference}\nTitle: {title}\n\nText:\n{text}"


# --- API call ----------------------------------------------------------------

_MAX_ATTEMPTS = 4
_RETRY_STATUSES = {429, 500, 502, 503, 504}

# together.ai's rate limit is dynamic per-org/per-model, not a fixed RPM --
# a burst of concurrent dispatches (the batch driver's thread pool) trips it
# even when the sustained rate is fine. Pacing request *dispatch* to no more
# than one every _min_interval seconds, shared across every worker thread,
# smooths that burst out. Tune via TOGETHER_MIN_REQUEST_INTERVAL, or per-run
# with set_min_request_interval (theo.llm_annotations wires up
# --min-request-interval on the CLI).
_DEFAULT_MIN_REQUEST_INTERVAL = float(os.environ.get("TOGETHER_MIN_REQUEST_INTERVAL", "0.5"))


class _RateLimiter:
    """Thread-safe pacing gate: callers are scheduled onto slots at least
    `interval` apart (tracked as a running clock, not "sleep interval after
    my last call"), so N concurrent workers dispatch spread out in time
    instead of firing a burst of N requests at once."""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def set_interval(self, interval: float) -> None:
        with self._lock:
            self._interval = interval

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_slot)
            self._next_slot = start + self._interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)


_rate_limiter = _RateLimiter(_DEFAULT_MIN_REQUEST_INTERVAL)


def set_min_request_interval(seconds: float) -> None:
    """Reconfigure the pacing gate shared by every _post_completion call in
    this process. Batch drivers call this once per run rather than threading
    the value through parse_text/request_annotation."""
    _rate_limiter.set_interval(seconds)


class TogetherError(RuntimeError):
    """The API call failed after retries, or returned unusable content."""


class TruncatedResponse(TogetherError):
    """The model hit max_tokens before closing the JSON. The maxItems caps
    on the schema's lists stop most degenerate repetition loops, but string
    fields are uncapped and the loops are stochastic -- the same request
    usually completes cleanly on retry (the batch driver retries, then
    falls back to smaller segments)."""


def api_key() -> str:
    """The together.ai key from the environment. Raises TogetherError when
    missing/empty -- batch drivers call this up front so a configuration
    mistake fails the run immediately instead of surfacing as thousands of
    identical per-pericope failures."""
    key = os.environ.get("TOGETHER_API_KEY")
    if not key:
        raise TogetherError("TOGETHER_API_KEY is not set (add it to .env)")
    return key


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Together's 429s carry x-ratelimit-reset: the dynamic per-model
    limiter's own count of seconds to wait before retrying. Trust it over a
    guessed exponential delay when it's present and parses."""
    value = response.headers.get("x-ratelimit-reset")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _post_completion(payload: dict, timeout: float) -> dict:
    """POST with backoff on rate limits, server errors, and transport
    failures, and dispatch paced by the shared rate limiter so a burst of
    worker threads doesn't itself trigger a 429. A 429's x-ratelimit-reset
    header is honored when present; other retryable failures fall back to
    exponential backoff (2, 4, 8s). Anything else non-2xx raises immediately.
    """
    last_error: Exception | None = None
    retry_after: float | None = None
    for attempt in range(_MAX_ATTEMPTS):
        if attempt:
            delay = retry_after if retry_after is not None else 2 ** attempt
            logger.warning(
                "together.ai request failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt, _MAX_ATTEMPTS, delay, last_error,
            )
            time.sleep(delay)
        retry_after = None
        _rate_limiter.wait()
        try:
            response = httpx.post(
                API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {api_key()}"},
                timeout=timeout,
            )
        except httpx.TransportError as exc:
            last_error = exc
            continue
        if response.status_code in _RETRY_STATUSES:
            last_error = TogetherError(f"HTTP {response.status_code}: {response.text[:500]}")
            if response.status_code == 429:
                retry_after = _retry_after_seconds(response)
            continue
        if response.status_code >= 400:
            # Non-retryable client error: the body says why (bad model, bad
            # schema, ...) -- surface it instead of a bare status code.
            raise TogetherError(f"HTTP {response.status_code}: {response.text[:500]}")
        return response.json()
    raise TogetherError(f"gave up after {_MAX_ATTEMPTS} attempts: {last_error}")


def _extract_json(content: str) -> dict:
    """The response should be bare JSON, but strip reasoning tags and
    markdown fences if the model added them anyway."""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content.strip())
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end <= start:
        raise TogetherError(f"no JSON object in response: {content[:200]!r}")
    return json.loads(content[start:end + 1])


def request_annotation(
    reference: str,
    title: str,
    text: str,
    model: str = DEFAULT_MODEL,
    timeout: float = 300.0,
) -> LlmAnnotation:
    """One passage through the LLM: returns the validated annotation, or
    raises TogetherError/ValidationError for the caller to handle (the batch
    driver logs and moves on rather than dying mid-corpus)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(reference, title, text)},
        ],
        # together.ai's constrained-JSON mode: type json_object plus the
        # schema itself (their native format, not OpenAI's json_schema nesting).
        "response_format": {"type": "json_object", "schema": LlmAnnotation.model_json_schema()},
        "temperature": 0.2,
        "max_tokens": 8192,
    }
    data = _post_completion(payload, timeout)
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise TruncatedResponse("response truncated at max_tokens")
    return LlmAnnotation.model_validate(_extract_json(choice["message"]["content"]))


# --- Shaping for storage -----------------------------------------------------

@dataclass(frozen=True)
class LlmParsedText:
    """An annotation shaped for the pericope_annotations columns, mirroring
    theo.parse.ParsedText where the columns overlap."""
    resolved: str
    entities: list[dict]              # same keys as spaCy rows; start/end/ustrong None
    svo: list[tuple[str, str, str]]
    extras: dict                      # the LLM-only enrichments, one JSONB blob


def to_parsed(annotation: LlmAnnotation) -> LlmParsedText:
    return LlmParsedText(
        resolved=annotation.resolved_text,
        entities=[
            {"text": e.text, "label": e.label, "start": None, "end": None, "ustrong": None}
            for e in annotation.entities
        ],
        svo=[(t.subject, t.verb, t.object) for t in annotation.svo],
        extras={
            "summary": annotation.summary,
            "genre": annotation.genre,
            "themes": annotation.themes,
            "keywords": annotation.keywords,
            "tone": annotation.tone,
            "speech_acts": [act.model_dump() for act in annotation.speech_acts],
        },
    )


def parse_text(
    reference: str,
    title: str,
    text: str,
    model: str = DEFAULT_MODEL,
) -> LlmParsedText:
    """Full LLM enrichment of one passage, storage-shaped."""
    return to_parsed(request_annotation(reference, title, text, model=model))


def _unique(items, key):
    """Order-preserving dedup by key(item)."""
    seen: set = set()
    kept = []
    for item in items:
        k = key(item)
        if k not in seen:
            seen.add(k)
            kept.append(item)
    return kept


def merge_parsed(parts: list[LlmParsedText]) -> LlmParsedText:
    """Combine the per-segment annotations of one pericope into a single
    storage-shaped record -- oversized pericopes are annotated in verse-range
    segments (see theo.llm_annotations) but stored as one row.

    Entities, themes, keywords, tone, and speech acts are deduplicated
    across segments preserving first-seen order; SVO triples likewise;
    resolved texts and one-sentence summaries are concatenated in segment
    order (a split pericope's summary is one sentence per segment); genre
    is the most common across segments, first-seen winning ties. The
    single-segment case passes everything through, so every stored row gets
    extras["segments"] regardless of whether it was split.
    """
    if not parts:
        raise ValueError("merge_parsed needs at least one part")
    genres = Counter(p.extras["genre"] for p in parts)
    return LlmParsedText(
        resolved=" ".join(p.resolved for p in parts),
        entities=_unique(
            (e for p in parts for e in p.entities),
            key=lambda e: (e["text"], e["label"]),
        ),
        svo=_unique((t for p in parts for t in p.svo), key=tuple),
        extras={
            "summary": " ".join(p.extras["summary"] for p in parts),
            "genre": genres.most_common(1)[0][0],
            "themes": _unique((t for p in parts for t in p.extras["themes"]), key=str),
            "keywords": _unique((k for p in parts for k in p.extras["keywords"]), key=str),
            "tone": _unique((t for p in parts for t in p.extras["tone"]), key=str),
            "speech_acts": _unique(
                (a for p in parts for a in p.extras["speech_acts"]),
                key=lambda a: tuple(sorted(a.items())),
            ),
            "segments": len(parts),
        },
    )
