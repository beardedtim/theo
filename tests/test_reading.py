"""Tests for theo.reading.

The `assemble_blocks` tests below are pure unit tests -- no DB, no `client`
fixture -- since assembly is a pure function over already-fetched rows. The
tests at the bottom are the usual integration style (see tests/conftest.py),
requiring the dev DB to be up and `uv run -m scripts.ingest_reading` already run.
"""

from theo.reading import _parse_word, assemble_blocks


def test_parse_word_plain():
    assert _parse_word("the") == {"word": "the"}


def test_parse_word_coded():
    assert _parse_word("Blessed*pn") == {"word": "Blessed", "codes": "pn"}


def test_assemble_plain_verse_no_codes():
    """A verse with zero markup still renders as one paragraph/line/run."""
    verse_rows = [
        {"chapt_num": 1, "verse_num": 5, "tokens": [
            {"word": "Then"}, {"word": "the"}, {"word": "Lord"}, {"word": "said"},
        ]},
    ]
    blocks = assemble_blocks(verse_rows, [])

    assert len(blocks) == 1
    assert blocks[0].kind == "paragraph"
    assert len(blocks[0].lines) == 1
    line = blocks[0].lines[0]
    assert line.indent == 0
    assert line.align == "left"
    assert len(line.runs) == 1
    run = line.runs[0]
    assert run.text == "Then the Lord said"
    assert run.chapter == 1
    assert run.verse == 5


def test_assemble_range_starting_mid_paragraph():
    """A range whose first token carries no p/l code (a real occurrence --
    26 of 1,189 NIV chapters open this way) must still render, not drop or
    crash on the leading text."""
    verse_rows = [
        {"chapt_num": 8, "verse_num": 1, "tokens": [
            {"word": "Then"}, {"word": "the"}, {"word": "Lord", "codes": "s"}, {"word": "said"},
        ]},
    ]
    blocks = assemble_blocks(verse_rows, [])

    assert len(blocks) == 1
    line = blocks[0].lines[0]
    assert line.indent == 0
    assert [(r.text, r.smallcaps) for r in line.runs] == [
        ("Then the", False),
        ("Lord", True),
        ("said", False),
    ]


def test_assemble_paragraph_start_mid_verse():
    verse_rows = [
        {"chapt_num": 29, "verse_num": 14, "tokens": [
            {"word": "Laban"}, {"word": "said"}, {"word": "to"}, {"word": "him,"},
            {"word": "You", "codes": "p"}, {"word": "are"}, {"word": "my"}, {"word": "own"}, {"word": "flesh"},
        ]},
    ]
    blocks = assemble_blocks(verse_rows, [])

    assert len(blocks) == 2
    assert blocks[0].lines[0].runs[0].text == "Laban said to him,"
    assert blocks[1].lines[0].runs[0].text == "You are my own flesh"


def test_assemble_poetry_stanza_indents():
    """Mirrors real NIV Psalm 1:1 markup: "Blessed*pn is the one who*ld
    does not walk...", first line indented once, continuation doubly."""
    verse_rows = [
        {"chapt_num": 1, "verse_num": 1, "tokens": [
            {"word": "Blessed", "codes": "pn"}, {"word": "is"}, {"word": "the"}, {"word": "one"},
            {"word": "who", "codes": "ld"}, {"word": "does"}, {"word": "not"}, {"word": "walk"},
        ]},
    ]
    blocks = assemble_blocks(verse_rows, [])

    assert len(blocks) == 1
    assert len(blocks[0].lines) == 2
    line1, line2 = blocks[0].lines
    assert (line1.indent, line1.align) == (1, "left")
    assert line1.runs[0].text == "Blessed is the one"
    assert (line2.indent, line2.align) == (2, "left")
    assert line2.runs[0].text == "who does not walk"


def test_assemble_styled_word_isolates_run():
    verse_rows = [
        {"chapt_num": 6, "verse_num": 6, "tokens": [
            {"word": "For", "codes": "pn"}, {"word": "the"}, {"word": "Lord", "codes": "s"},
            {"word": "watches"}, {"word": "over"},
        ]},
    ]
    blocks = assemble_blocks(verse_rows, [])

    line = blocks[0].lines[0]
    assert [(r.text, r.smallcaps) for r in line.runs] == [
        ("For the", False),
        ("Lord", True),
        ("watches over", False),
    ]


def test_assemble_consecutive_unstyled_verses_keep_distinct_verse_numbers():
    """Regression: two consecutive verses with zero codes each (the common
    case) must still produce two runs, each carrying its own verse number --
    not merge into one run that can only tag a single verse."""
    verse_rows = [
        {"chapt_num": 1, "verse_num": 1, "tokens": [
            {"word": "In", "codes": "p"}, {"word": "the"}, {"word": "beginning"},
        ]},
        {"chapt_num": 1, "verse_num": 2, "tokens": [
            {"word": "Now"}, {"word": "the"}, {"word": "earth"},
        ]},
    ]
    blocks = assemble_blocks(verse_rows, [])

    assert len(blocks) == 1
    line = blocks[0].lines[0]
    assert len(line.runs) == 2
    assert (line.runs[0].verse, line.runs[0].text) == (1, "In the beginning")
    assert (line.runs[1].verse, line.runs[1].text) == (2, "Now the earth")


def test_assemble_heading_mid_chapter():
    """Regression: the real Genesis 2 data anchors the "Adam and Eve" heading
    at anchor_verse_num=3 -- the verse whose text preceded the heading in the
    source stream, per its own r component -- even though the heading (and
    the pericope it starts) belongs immediately before verse 4, not verse 3."""
    verse_rows = [
        {"chapt_num": 2, "verse_num": 3, "tokens": [
            {"word": "Then", "codes": "p"}, {"word": "God"}, {"word": "blessed"},
        ]},
        {"chapt_num": 2, "verse_num": 4, "tokens": [
            {"word": "Adam", "codes": "p"}, {"word": "and"}, {"word": "Eve"},
        ]},
    ]
    heading_rows = [
        {"chapt_num": 2, "anchor_verse_num": 3, "order_num": 50, "level": 2, "heading_text": "Adam and Eve"},
    ]
    blocks = assemble_blocks(verse_rows, heading_rows)

    assert [b.kind for b in blocks] == ["paragraph", "heading", "paragraph"]
    assert blocks[0].lines[0].runs[0].text == "Then God blessed"
    assert blocks[1].text == "Adam and Eve"
    assert blocks[1].level == 2
    assert blocks[2].lines[0].runs[0].text == "Adam and Eve"


def test_assemble_stacked_headings_preserve_order_num_not_level():
    """Psalm 1:0 in the real data has three headings anchored at once
    (h=1, h=2.5, h=3) -- order between them must follow `order_num`, not an
    assumption that ascending level always matches display order."""
    verse_rows = [
        {"chapt_num": 1, "verse_num": 1, "tokens": [{"word": "Blessed", "codes": "pn"}, {"word": "is"}]},
    ]
    heading_rows = [
        {"chapt_num": 1, "anchor_verse_num": 0, "order_num": 3, "level": 3, "heading_text": "Psalms 1-41"},
        {"chapt_num": 1, "anchor_verse_num": 0, "order_num": 1, "level": 1, "heading_text": "Psalm 1"},
        {"chapt_num": 1, "anchor_verse_num": 0, "order_num": 2, "level": 2.5, "heading_text": "BOOK I"},
    ]
    blocks = assemble_blocks(verse_rows, heading_rows)

    headings = [b for b in blocks if b.kind == "heading"]
    assert [h.text for h in headings] == ["Psalm 1", "BOOK I", "Psalms 1-41"]


def test_assemble_chapter_opening_heading_present_at_verse_start_1():
    """Regression: a heading anchored at verse 0 ("before verse 1") must
    still appear when the fetched range starts at verse_start=1 -- the most
    common query shape. A naive tuple-range SQL filter on anchor_verse_num
    would otherwise silently exclude it."""
    verse_rows = [
        {"chapt_num": 1, "verse_num": 1, "tokens": [{"word": "In", "codes": "p"}, {"word": "the"}, {"word": "beginning"}]},
    ]
    heading_rows = [
        {"chapt_num": 1, "anchor_verse_num": 0, "order_num": 1, "level": 1, "heading_text": "Genesis 1"},
    ]
    blocks = assemble_blocks(verse_rows, heading_rows)

    assert blocks[0].kind == "heading"
    assert blocks[0].text == "Genesis 1"
    assert blocks[1].kind == "paragraph"


# --- Integration tests (require the dev DB up + `uv run -m scripts.ingest_reading`) ---

def test_reading_genesis_1_has_headings_and_paragraphs(client):
    response = client.get("/reading/Genesis/1/1/1/31")

    assert response.status_code == 200
    blocks = response.json()
    kinds = {b["kind"] for b in blocks}
    assert kinds == {"heading", "paragraph"}
    heading_texts = [b["text"] for b in blocks if b["kind"] == "heading"]
    assert "Genesis 1" in heading_texts
    assert "The Beginning" in heading_texts


def test_reading_psalm_1_has_indented_poetry_lines(client):
    response = client.get("/reading/Psalm/1/1/1/6")

    assert response.status_code == 200
    blocks = response.json()
    indents = {
        line["indent"]
        for b in blocks if b["kind"] == "paragraph"
        for line in b["lines"]
    }
    assert indents & {1, 2}


def test_reading_has_red_letter_words(client):
    response = client.get("/reading/John/1/38/1/38")

    assert response.status_code == 200
    blocks = response.json()
    runs = [
        r for b in blocks if b["kind"] == "paragraph"
        for line in b["lines"] for r in line["runs"]
    ]
    assert any(r["red_letter"] for r in runs)


def test_reading_unsupported_translation_404s(client):
    response = client.get("/reading/Genesis/1/1/1/31?translation=ESV")

    assert response.status_code == 404


def test_reading_bad_book_404s(client):
    response = client.get("/reading/NotABook/1/1/1/10")

    assert response.status_code == 404
