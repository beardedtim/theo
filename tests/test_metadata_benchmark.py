import pytest

from theo.metadata_benchmark import (
    _form_surface_strings,
    _normalize,
    evaluate_entities,
    list_pipelines,
    worst,
)
from theo.step_names import TipnrForm, TipnrRecord


def _record(name="Chilion", forms=()):
    return TipnrRecord(
        tipnr_key=f"{name}@Rut.1.2-=H0000", ustrong="H0000", name=name, category="person",
        entity_type="Male", description=None, parents=None, siblings=None, partners=None,
        offspring=None, tribe=None, openbible_name=None, founder=None, inhabitants=None,
        geo_area=None, latitude=None, longitude=None, summary_html=None, briefest=None,
        brief=None, short_desc=None, article_html=None, forms=forms,
    )


def _form(translations, seq=0):
    return TipnrForm(
        seq=seq, significance="Named", unique_name=None, strongs_raw=None,
        dstrong=None, estrong=None, original=None, translations=translations, refs=(),
    )


def test_normalize_strips_articles_and_punctuation():
    assert _normalize("the LORD") == "lord"
    assert _normalize("  Boaz.  ") == "boaz"
    assert _normalize("An Elder") == "elder"


def test_form_surface_strings_scopes_to_the_given_translation():
    record = _record("Chilion")
    form = _form("Chilion =ESV,KJV; Kilion =NIV")

    assert _form_surface_strings(record, form, "NIV") == {"Kilion"}
    assert _form_surface_strings(record, form, "KJV") == {"Chilion"}
    assert _form_surface_strings(record, form, "ESV") == {"Chilion"}


def test_form_surface_strings_falls_back_to_canonical_name_when_untagged():
    record = _record("Amminadab")
    form = _form("Amminadab")  # no "=CODE" at all -- one spelling everywhere

    assert _form_surface_strings(record, form, "NIV") == {"Amminadab"}


def test_form_surface_strings_drops_non_proper_noun_renderings():
    # theo.parse._NAME_RE requires a capitalized, proper-noun-shaped string;
    # a lowercase translated-word rendering (TIPNR carries these for some
    # place names) must not leak into ground truth.
    record = _record("Ebenezer")
    form = _form("stone of help =NIV")

    assert _form_surface_strings(record, form, "NIV") == set()


def test_evaluate_entities_against_real_db_smoke():
    """Exercises the real derivation against the live dev DB (see
    tests/conftest.py -- this suite assumes one is up and ingested)."""
    pipelines = list_pipelines()
    assert pipelines  # at least one annotation pipeline has been run

    report = evaluate_entities(pipelines[0], book="Ruth")

    assert report.n_pericopes > 0
    assert report.tp > 0
    assert 0.0 <= report.precision <= 1.0
    assert 0.0 <= report.recall <= 1.0
    assert 0.0 <= report.f1 <= 1.0
    assert report.tp + report.fn == sum(len(o.expected) for o in report.outcomes)
    assert report.tp + report.fp == sum(len(o.extracted) for o in report.outcomes)


def test_worst_ranks_by_count_of_the_given_field():
    report = evaluate_entities(list_pipelines()[0], book="Ruth")

    top = worst(report, by="missed", limit=2)
    assert len(top) <= 2
    assert all(o.missed for o in top)
    if len(top) == 2:
        assert len(top[0].missed) >= len(top[1].missed)
