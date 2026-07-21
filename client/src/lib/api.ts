// Thin client for the Theo FastAPI service (theo/server.py).

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:8000";

export interface Verse {
  translation: string;
  book: string;
  chapter: number;
  verse: number;
  text: string;
}

export interface Pericope {
  id: string;
  title: string;
  book: number;
  chapter_start: number;
  verse_start: number;
  chapter_end: number;
  verse_end: number;
}

export interface SearchResult {
  pericope: Pericope;
  verses: Verse[];
  score: number;
}

export type SearchMode = "semantic" | "bm25" | "hybrid";

export interface Person {
  id: string;
  name: string;
  display_title: string;
  gender: string | null;
  also_called: string | null;
  birth_year: number | null;
  death_year: number | null;
  dictionary_text: string | null;
}

export interface Place {
  id: string;
  kjv_name: string;
  display_title: string;
  feature_type: string | null;
  feature_sub_type: string | null;
  latitude: number | null;
  longitude: number | null;
  dictionary_text: string | null;
}

export interface Event {
  id: string;
  title: string;
  start_date: string | null;
  duration: string | null;
  sort_key: number | null;
}

export interface EventDetail {
  event: Event;
  participants: Person[];
  locations: Place[];
}

export interface PeopleGroup {
  id: string;
  group_name: string;
}

export interface GroupDetail {
  group: PeopleGroup;
  members: Person[];
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(path: string, params: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(API_BASE_URL + path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, body?.detail ?? response.statusText);
  }

  return response.json() as Promise<T>;
}

export interface SearchParams {
  q: string;
  mode?: SearchMode;
  limit?: number;
  translation?: string;
}

export function search({ q, mode, limit, translation }: SearchParams): Promise<SearchResult[]> {
  return request<SearchResult[]>("/search", { q, mode, limit, translation });
}

export interface ListVersesParams {
  book: string;
  chapter: number;
  verseStart?: number;
  verseEnd?: number;
  translation?: string;
}

export function listVerses({
  book,
  chapter,
  verseStart,
  verseEnd,
  translation,
}: ListVersesParams): Promise<Verse[]> {
  const path =
    verseStart !== undefined && verseEnd !== undefined
      ? `/verses/${encodeURIComponent(book)}/${chapter}/${verseStart}/${verseEnd}`
      : `/verses/${encodeURIComponent(book)}/${chapter}`;

  return request<Verse[]>(path, { translation });
}

// --- Theographic data: people, places, events, and people groups referenced
// in a verse range, plus browsing events and people groups directly. ---

export interface VerseRangeParams {
  book: string | number;
  chapterStart: number;
  verseStart: number;
  chapterEnd: number;
  verseEnd: number;
}

function rangePath(entity: string, { book, chapterStart, verseStart, chapterEnd, verseEnd }: VerseRangeParams): string {
  return `/${entity}/${encodeURIComponent(String(book))}/${chapterStart}/${verseStart}/${chapterEnd}/${verseEnd}`;
}

export function listEvents(): Promise<Event[]> {
  return request<Event[]>("/events", {});
}

export function getEvent(eventId: string): Promise<EventDetail> {
  return request<EventDetail>(`/event/${encodeURIComponent(eventId)}`, {});
}

export function listPeopleGroups(): Promise<PeopleGroup[]> {
  return request<PeopleGroup[]>("/people-groups", {});
}

export function getPeopleGroup(groupId: string): Promise<GroupDetail> {
  return request<GroupDetail>(`/people-groups/${encodeURIComponent(groupId)}`, {});
}

// --- STEPBible data: TIPNR proper nouns and the Strong's brief lexicons. ---

export interface StepName {
  id: string;
  ustrong: string;
  name: string;
  category: "person" | "place" | "other";
  entity_type: string | null;
  description: string | null;
  brief: string | null;
}

export interface StepNameForm {
  significance: string;
  unique_name: string | null;
  dstrong: string | null;
  estrong: string | null;
  original: string | null;
  translations: string | null;
}

export interface StepNameRef {
  book: number;
  chapt_num: number;
  verse_num: number;
}

export interface StepNameDetail {
  id: string;
  ustrong: string;
  name: string;
  category: "person" | "place" | "other";
  entity_type: string | null;
  description: string | null;
  parents: string | null;
  siblings: string | null;
  partners: string | null;
  offspring: string | null;
  tribe: string | null;
  openbible_name: string | null;
  founder: string | null;
  inhabitants: string | null;
  geo_area: string | null;
  latitude: number | null;
  longitude: number | null;
  summary_html: string | null;
  briefest: string | null;
  brief: string | null;
  short_desc: string | null;
  article_html: string | null;
  forms: StepNameForm[];
  refs: StepNameRef[];
}

export function getStepName(nameId: string): Promise<StepNameDetail> {
  return request<StepNameDetail>(`/name/${encodeURIComponent(nameId)}`, {});
}

export interface LexiconEntry {
  dstrong: string;
  estrong: string;
  ustrong: string;
  ustrong_raw: string | null;
  relation: string | null;
  language: "hebrew" | "greek";
  original: string | null;
  transliteration: string | null;
  morph: string | null;
  gloss: string | null;
  meaning_html: string | null;
}

export function searchLexicon(q: string, limit?: number): Promise<LexiconEntry[]> {
  return request<LexiconEntry[]>("/lexicon", { q, limit });
}

export function getLexiconEntries(strongs: string): Promise<LexiconEntry[]> {
  return request<LexiconEntry[]>(`/lexicon/${encodeURIComponent(strongs)}`, {});
}

// --- Combined metadata: everything known about a passage in one call. ---

export interface AnnotationEntity {
  text: string;
  label: string;
  start: number | null; // null for LLM-pipeline rows (no character offsets)
  end: number | null;
  ustrong: string | null;
}

export interface SpeechAct {
  speaker: string;
  addressee: string;
  act: string;
}

// LLM-only enrichments; null on spaCy-pipeline rows.
export interface AnnotationExtras {
  summary: string; // one sentence per annotated segment (usually one)
  genre: string;
  themes: string[];
  keywords: string[];
  tone: string[];
  speech_acts: SpeechAct[];
  segments?: number; // how many LLM requests the pericope was split into
}

export interface PericopeAnnotation {
  pericope_id: string;
  translation: string;
  pipeline: string;
  resolved_text: string | null;
  entities: AnnotationEntity[];
  svo: [string, string, string][];
  extras: AnnotationExtras | null;
}

// One mentioned person/place/group/thing, source-prioritized on the server
// (STEP proper nouns first, theographic knowledge graph as fallback). The
// common fields drive list views; `data` is the source-native record for
// detail views, discriminated by (source, kind).
export type EntityKind = "person" | "place" | "group" | "other";

interface EntityBase {
  name: string;
  description: string | null;
}

export type MetadataEntity =
  | (EntityBase & { source: "step"; kind: EntityKind; ustrong: string; data: StepName })
  | (EntityBase & { source: "theographic"; kind: "person"; ustrong: null; data: Person })
  | (EntityBase & { source: "theographic"; kind: "place"; ustrong: null; data: Place })
  | (EntityBase & { source: "theographic"; kind: "group"; ustrong: null; data: PeopleGroup });

export interface VerseMetadata {
  book: number;
  chapter_start: number;
  verse_start: number;
  chapter_end: number;
  verse_end: number;
  pericopes: Pericope[];
  entities: MetadataEntity[];
  events: Event[];
  lexicon: Record<string, LexiconEntry[]>;
  annotations: PericopeAnnotation[]; // one per overlapping pericope (best pipeline)
}

export function getMetadataForRange(range: VerseRangeParams, translation?: string): Promise<VerseMetadata> {
  return request<VerseMetadata>(rangePath("metadata", range), { translation });
}

export function getMetadataForPericope(pericopeId: string, translation?: string): Promise<VerseMetadata> {
  return request<VerseMetadata>(`/metadata/pericope/${encodeURIComponent(pericopeId)}`, { translation });
}

// --- Reading view: paragraph/poetry layout, section headings, and inline
// styling for a verse range. NIV only for now. ---

export interface ReadingRun {
  text: string;
  chapter: number | null;
  verse: number | null;
  smallcaps: boolean;
  italic: boolean;
  bold: boolean;
  red_letter: boolean;
}

export interface ReadingLine {
  indent: number;
  align: "left" | "center" | "right";
  runs: ReadingRun[];
}

export interface HeadingBlock {
  kind: "heading";
  level: number;
  text: string;
}

export interface ParagraphBlock {
  kind: "paragraph";
  lines: ReadingLine[];
}

export type ReadingBlock = HeadingBlock | ParagraphBlock;

export function getReading(range: VerseRangeParams, translation = "NIV"): Promise<ReadingBlock[]> {
  return request<ReadingBlock[]>(rangePath("reading", range), { translation });
}
