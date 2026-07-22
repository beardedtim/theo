import { bookName } from "@/lib/bible";
import type { Note } from "@/lib/api";

/** A note's URL under /notes/:slug -- slugs are a file path (e.g.
 * "pentateuch/authorship") and can contain "/", so each segment is encoded
 * individually rather than encoding the whole slug (which would turn "/"
 * into "%2F" and collapse it to one path segment). */
export function noteHref(slug: string): string {
  return `/notes/${slug.split("/").map(encodeURIComponent).join("/")}`;
}

/** A note's verse-range scope as display text, e.g. "Exodus 1:1–15:21", or
 * null for a note scoped to a passage group instead (see note.passage_group_id). */
export function noteRangeLabel(note: Note): string | null {
  if (note.book === null || note.chapter_start === null || note.verse_start === null) {
    return null;
  }
  const book = bookName(note.book);
  const { chapter_start, verse_start, chapter_end, verse_end } = note;
  if (chapter_start === chapter_end) {
    return verse_start === verse_end
      ? `${book} ${chapter_start}:${verse_start}`
      : `${book} ${chapter_start}:${verse_start}-${verse_end}`;
  }
  return `${book} ${chapter_start}:${verse_start}–${chapter_end}:${verse_end}`;
}

/** Note bodies are stored as raw markdown (rendering is a client concern --
 * see theo/notes.py); notes are short, paragraph-only commentary, so a
 * blank-line split is enough to get Prose's paragraph spacing without
 * pulling in a full markdown parser. */
export function noteParagraphs(body: string): string[] {
  return body
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
}
