"""Unit tests for theo.bm25.sanitize_query. Pure function, no DB needed --
see the endpoint-level regression tests in test_search.py, test_dictionary.py,
test_lexicon.py, test_step_names.py, and test_pericopes.py for proof that
sanitized queries actually stop pg_search's `@@@` operator from 500ing.
"""

from theo.bm25 import sanitize_query


def test_sanitize_apostrophe():
    assert sanitize_query("shepherd's heart") == "shepherd s heart"


def test_sanitize_verse_reference():
    assert sanitize_query("John 3:16") == "John 3 16"


def test_sanitize_unbalanced_quote():
    assert sanitize_query('steadfast "love') == "steadfast love"


def test_sanitize_to_empty_string():
    assert sanitize_query("()") == ""


def test_sanitize_lowercases_bare_operator_word():
    assert sanitize_query("shepherd AND") == "shepherd and"
