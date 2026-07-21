"""NLP enrichment pipeline: spaCy (en_core_web_trf) + fastcoref.

Produces, for a passage of text:
- entities: NER spans, boosted by a gazetteer built from TIPNR proper nouns
  (theo.step_names) so biblical names generic models miss are recognized and
  carry their uStrong id back to the `step_names` table;
- resolved text: the passage with coreferences replaced by their antecedents
  ("He stayed there" -> "Moses stayed on the mountain");
- SVO triples: (subject, verb lemma, object), extracted from the dependency
  parse of the *resolved* text so pronoun-heavy narrative still yields
  useful triples.

Pure NLP -- no database access. theo.annotations handles storage. The
pipeline is loaded lazily via get_nlp() (a transformer + coref model; first
call takes ~10s), so importing this module stays cheap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from theo.step_names import TipnrRecord, parse_tipnr

# spacy/fastcoref/torch are imported inside get_nlp(), not here: the API
# Docker image deliberately omits the NLP dependency group (annotation runs
# on the dev machine), and theo.server transitively imports this module via
# theo.metadata -> theo.annotations, so it must stay importable without them.
if TYPE_CHECKING:
    from spacy.language import Language
    from spacy.tokens import Doc

# Bump when the models or extraction logic change in a way that should
# invalidate stored annotations; theo.annotations keys rows on this.
PIPELINE_VERSION = "en_core_web_trf+fastcoref/v1"

# TIPNR entity_type -> NER label for gazetteer matches.
_TYPE_LABELS = {
    "Male": "PERSON",
    "Female": "PERSON",
    "Group": "NORP",
    "Place": "LOC",
    "Language": "LANGUAGE",
    "Time": "DATE",
    "Supernatural": "PERSON",
    "Musical": "WORK_OF_ART",
    "Star": "LOC",
    "Title": "PERSON",
}
# Gazetteer strings must look like proper nouns: capitalized, and not so
# short or generic that they'd tag ordinary prose (TIPNR includes renderings
# like "stone" for translated place names -- lowercase, so excluded here).
_NAME_RE = re.compile(r"^[A-Z][A-Za-z'’.\- ]{1,40}$")


def _gazetteer_strings(record: TipnrRecord) -> set[str]:
    """Every way this entity is written in an English translation: its
    unified name plus each form's ESV/KJV/NIV renderings."""
    names = {record.name}
    for form in record.forms:
        for segment in (form.translations or "").split(";"):
            names.add(segment.split("=")[0].strip())
    return {n for n in names if _NAME_RE.match(n)}


# Bare divine terms always resolve to TIPNR's Deity record ("LORD"). They
# also appear as compound-name renderings inside other records (Israel via
# El-Elohe-Israel, Jesus via "Lord") whose much longer ref lists would
# otherwise win the ranking below -- the LORD record is the one entity whose
# ref list the source abbreviates, so its weight underrepresents it.
_DIVINE_STRINGS = {"God", "Lord", "LORD", "Almighty", "Most High"}


def _gazetteer_patterns() -> list[dict]:
    """EntityRuler patterns from the TIPNR file. Same-named entities (e.g.
    the three Abdis) collapse to the record whose unified name matches the
    string exactly, then to the one with the most verse references --
    verse-level ground truth lives in step_name_verses, this id is just the
    best guess for running text."""
    best: dict[str, tuple[tuple[bool, int], dict]] = {}
    for record in parse_tipnr():
        weight = sum(len(form.refs) for form in record.forms)
        label = _TYPE_LABELS.get(record.entity_type or "", "MISC")
        for name in _gazetteer_strings(record):
            if name in _DIVINE_STRINGS and record.name != "LORD":
                continue
            rank = (name == record.name, weight)
            if name not in best or best[name][0] < rank:
                best[name] = (rank, {"label": label, "pattern": name, "id": record.ustrong})
    return [pattern for _, pattern in best.values()]


@lru_cache(maxsize=1)
def get_nlp() -> Language:
    """The full pipeline: en_core_web_trf with a TIPNR entity_ruler ahead of
    NER (ruler matches win; the statistical NER fills in around them) and
    fastcoref at the end. Runs on GPU when one is available."""
    import spacy
    import torch
    from fastcoref import spacy_component  # noqa: F401  -- registers the "fastcoref" pipe

    spacy.prefer_gpu()
    nlp = spacy.load("en_core_web_trf")
    ruler = nlp.add_pipe("entity_ruler", before="ner")
    ruler.add_patterns(_gazetteer_patterns())
    nlp.add_pipe(
        "fastcoref",
        config={"device": "cuda:0" if torch.cuda.is_available() else "cpu"},
    )
    return nlp


def process_text(txt: str) -> Doc:
    """Returns a spacy Document with all pipeline processing (coref, etc) done"""
    return get_nlp()(txt, component_cfg={"fastcoref": {"resolve_text": True}})


def _phrase(token) -> str:
    """A token plus its compound/possessive left-children, e.g. the object
    token "Egypt" under "land of Egypt" stays "Egypt" but "Simon" in "Simon
    Peter said" becomes "Simon Peter"."""
    parts = [t.text for t in token.lefts if t.dep_ in ("compound", "poss")]
    parts.append(token.text)
    return " ".join(parts)


def generate_svo(doc: Doc) -> list[tuple[str, str, str]]:
    """(subject, verb lemma, object) triples from a parsed Doc. Run this on
    coref-RESOLVED text -- on raw text most subjects are just pronouns."""
    triples = []
    for token in doc:
        if token.pos_ != "VERB":
            continue
        subjects = [c for c in token.children if c.dep_ in ("nsubj", "nsubjpass")]
        objects = [c for c in token.children if c.dep_ in ("dobj", "attr", "dative")]
        for prep in (c for c in token.children if c.dep_ == "prep"):
            objects.extend(gc for gc in prep.children if gc.dep_ == "pobj")
        triples.extend(
            (_phrase(subject), token.lemma_, _phrase(obj))
            for subject in subjects
            for obj in objects
        )
    return triples


@dataclass(frozen=True)
class TextEntity:
    text: str
    label: str
    start: int          # character offsets into the raw text
    end: int
    ustrong: str | None  # step_names.ustrong for gazetteer matches, else None


@dataclass(frozen=True)
class ParsedText:
    raw: str
    resolved: str
    entities: list[TextEntity]
    svo: list[tuple[str, str, str]]


def parse_texts(texts: list[str], batch_size: int = 16) -> list[ParsedText]:
    """Full enrichment of a batch of passages: entities off the raw text,
    SVO off the coref-resolved text. Batched through nlp.pipe so the
    transformer sees full batches -- markedly faster than one-at-a-time on
    GPU."""
    nlp = get_nlp()
    docs = list(nlp.pipe(
        texts,
        batch_size=batch_size,
        component_cfg={"fastcoref": {"resolve_text": True}},
    ))
    resolveds = [doc._.resolved_text or txt for doc, txt in zip(docs, texts)]

    # Second pass over the resolved texts for their dependency parses; coref
    # would be a no-op there, so skip that component.
    with nlp.select_pipes(disable=["fastcoref"]):
        svo_docs = list(nlp.pipe(resolveds, batch_size=batch_size))

    return [
        ParsedText(
            raw=txt,
            resolved=resolved,
            entities=[
                TextEntity(
                    text=ent.text,
                    label=ent.label_,
                    start=ent.start_char,
                    end=ent.end_char,
                    ustrong=ent.ent_id_ or None,
                )
                for ent in doc.ents
            ],
            svo=generate_svo(svo_doc),
        )
        for txt, doc, resolved, svo_doc in zip(texts, docs, resolveds, svo_docs)
    ]


def parse_text(txt: str) -> ParsedText:
    """Full enrichment of one passage; see parse_texts."""
    return parse_texts([txt])[0]
