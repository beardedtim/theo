"""CLI: regenerate client/public/sitemap.xml from the wouter route table plus
every notes/*.md file. Doesn't touch the database or read the notes table --
it walks the notes/ folder directly and derives each slug with
theo.notes.slug_for, the same function ingest_notes.py uses, so a note's
sitemap URL always matches the /notes/{slug} route it actually resolves to.

Static routes are the top-level entries in client/src/App.tsx's <Switch>
that aren't in there as a wildcard fallback (i.e. everything but /notes/*,
which the notes/ walk covers per-slug instead) -- update STATIC_ROUTES here
if that <Switch> changes.

Re-run after adding/renaming/removing a note file, or after changing
App.tsx's top-level routes:
    uv run -m scripts.generate_sitemap
"""

import subprocess
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import tyro

from theo.notes import slug_for

STATIC_ROUTES = ["/", "/search", "/verses", "/notes", "/lexicon"]


def _last_commit_date(path: Path) -> str | None:
    """Last commit date for `path` (YYYY-MM-DD), or None if it isn't tracked
    yet (a new, uncommitted note) -- sitemap <lastmod> is optional, and a
    file's mtime after a fresh `git clone` reflects checkout time, not the
    content's actual last edit, so git history is the only accurate source."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ad", "--date=short", "--", str(path)],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


def main(
    base_url: str = "https://sproutfaith.com",
    notes_dir: Path = Path("notes"),
    out: Path = Path("client/public/sitemap.xml"),
) -> None:
    """CLI: regenerate the sitemap.

    Args:
        base_url: Site origin sitemap <loc> entries are built from (no
            trailing slash).
        notes_dir: Root notes are read from -- same default as ingest_notes.py.
        out: Where to write the sitemap. client/public/ so Vite copies it to
            the build root; nginx serves it unprefixed at /sitemap.xml.
    """
    base_url = base_url.rstrip("/")
    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")

    today = date.today().isoformat()
    for route in STATIC_ROUTES:
        url = ET.SubElement(urlset, "url")
        ET.SubElement(url, "loc").text = f"{base_url}{route}"
        ET.SubElement(url, "lastmod").text = today

    note_paths = sorted(notes_dir.glob("**/*.md"))
    for path in note_paths:
        slug = slug_for(path, notes_dir)
        url = ET.SubElement(urlset, "url")
        ET.SubElement(url, "loc").text = f"{base_url}/notes/{slug}"
        lastmod = _last_commit_date(path)
        if lastmod:
            ET.SubElement(url, "lastmod").text = lastmod

    ET.indent(urlset)
    out.write_bytes(ET.tostring(urlset, encoding="utf-8", xml_declaration=True))
    print(f"Wrote {out} ({len(STATIC_ROUTES)} static routes + {len(note_paths)} notes).")


if __name__ == "__main__":
    tyro.cli(main)
