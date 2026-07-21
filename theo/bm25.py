"""Sanitize free-text search input before it reaches pg_search's `@@@`
operator.

`@@@`'s right-hand side isn't matched as literal text -- it's parsed as
full tantivy query syntax (quoted phrases, `field:value` clauses,
parenthesized groups, `AND`/`OR`/`NOT` boolean operators, wildcards, ...).
User-typed search boxes routinely contain characters that are meaningful
in that syntax but weren't intended as such -- an apostrophe in "shepherd's
heart", a colon in a verse reference like "John 3:16", a trailing
uppercase "AND" -- and an unbalanced or otherwise malformed one is a hard
parse error at the database, surfacing to the caller as an HTTP 500
instead of an empty or partial result.

None of Theo's search endpoints expose a real boolean-query UI, so
`sanitize_query` deliberately trades away tantivy's query-syntax features
(phrase quoting, boosting, field targeting, ...) for a transform that can
never make `@@@` error.
"""

from __future__ import annotations

import re

# Characters tantivy's query parser treats as syntax, not literal text.
# Replaced with a space -- not deleted: the default tokenizer already
# splits indexed text on non-alphanumeric characters, so "shepherd's" is
# indexed as the two tokens ["shepherd", "s"]. Replacing the apostrophe
# with a space keeps the query matching that; deleting it would instead
# produce the single token "shepherds", which never matches.
_SYNTAX_CHARS = re.compile(r'''[`'":()\[\]{}^~*?\\!+\-&|<>=]''')

# Bare/trailing uppercase boolean operators are a parse error (e.g. a
# query ending in "... AND" with nothing following it). Lowercased,
# they're just ordinary terms -- and since the tokenizer lowercases
# everything anyway, this doesn't change what a genuine boolean query
# would otherwise have matched.
_OPERATOR_WORDS = {"AND", "OR", "NOT", "TO", "IN"}


def sanitize_query(query: str) -> str:
    """Strip tantivy query-syntax out of free-text search input so it can
    be passed to `@@@` without risking a parse-error 500.

    This is not a query-syntax sanitizer in the sense of preserving
    intent -- boosting, phrase quoting, field targeting, etc. are simply
    lost -- just a guarantee that the result is always safe to search
    literally. May return an empty string (e.g. for a query that was pure
    syntax, like "()"); callers should treat that as "no results" rather
    than querying `@@@` with an empty string, which is itself a parse
    error.
    """
    despecialized = _SYNTAX_CHARS.sub(" ", query)
    tokens = [token.lower() if token in _OPERATOR_WORDS else token for token in despecialized.split()]
    return " ".join(tokens)
