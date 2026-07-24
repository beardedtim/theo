import { useEffect, useState, type SubmitEvent } from "react";
import { useSearch, useSearchParams } from "wouter";
import {
  Alert,
  Field,
  Heading,
  HStack,
  Input,
  Separator,
  Spinner,
  Stack,
  Text,
  VStack,
  Button,
} from "@chakra-ui/react";
import {
  ApiError,
  getReading,
  listVerses,
  type ReadingBlock,
  type Verse,
} from "@/lib/api";
import { ReferencesPanel } from "@/components/ReferencesPanel";
import { ReadingView } from "@/components/ReadingView";

interface FetchArgs {
  book: string;
  chapter: number;
  verseStart?: number;
  verseEnd?: number;
  translation: string;
}

function VersesPage() {
  const queryString = useSearch();
  const [_, setUrlSearchParams] = useSearchParams();

  const [book, setBook] = useState("");
  const [chapter, setChapter] = useState("");
  const [verseStart, setVerseStart] = useState("");
  const [verseEnd, setVerseEnd] = useState("");
  const [translation, setTranslation] = useState("NIV");
  // Set only when the current passage came from a "Read in context" link on
  // the Search page, so ReferencesPanel can use the server's resolved
  // pericope range instead of the (possibly hand-edited) form fields.
  const [pericopeId, setPericopeId] = useState<string | null>(null);

  const [verses, setVerses] = useState<Verse[] | null>(null);
  const [readingBlocks, setReadingBlocks] = useState<ReadingBlock[] | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function fetchVerses({
    book,
    chapter,
    verseStart,
    verseEnd,
    translation,
  }: FetchArgs) {
    setLoading(true);
    setError(null);
    setReadingBlocks(null);
    try {
      const data = await listVerses({
        book,
        chapter,
        verseStart,
        verseEnd,
        translation,
      });
      setVerses(data);

      // Reading-formatted layout only exists for NIV so far. Best-effort:
      // if it's unavailable for this range, silently fall back to the flat
      // verse list rather than surfacing an error for a purely cosmetic
      // upgrade.
      if (data.length > 0 && translation.toUpperCase() === "NIV") {
        try {
          const blocks = await getReading({
            book: data[0].book,
            chapterStart: data[0].chapter,
            verseStart: data[0].verse,
            chapterEnd: data[data.length - 1].chapter,
            verseEnd: data[data.length - 1].verse,
          });
          setReadingBlocks(blocks);
        } catch {
          setReadingBlocks(null);
        }
      }
    } catch (err) {
      setVerses(null);
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Is the API running?",
      );
    } finally {
      setLoading(false);
    }
  }

  // Deep link from a Search result: /verses?book=...&chapter=...&verseStart=...&verseEnd=...&translation=...&pericopeId=...
  useEffect(() => {
    const params = new URLSearchParams(queryString);
    const qBook = params.get("book");
    const qChapter = params.get("chapter");
    if (!qBook || !qChapter) return;

    const qVerseStart = params.get("verseStart") ?? "";
    const qVerseEnd = params.get("verseEnd") ?? "";
    const qTranslation = params.get("translation") || "NIV";

    setBook(qBook);
    setChapter(qChapter);
    setVerseStart(qVerseStart);
    setVerseEnd(qVerseEnd);
    setTranslation(qTranslation);
    setPericopeId(params.get("pericopeId"));

    void fetchVerses({
      book: qBook,
      chapter: Number(qChapter),
      verseStart: qVerseStart ? Number(qVerseStart) : undefined,
      verseEnd: qVerseEnd ? Number(qVerseEnd) : undefined,
      translation: qTranslation,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryString]);

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!book.trim() || !chapter.trim()) return;

    setPericopeId(null);

    // Set url params so we have this in history
    const args: any = {
      book: book.trim(),
      chapter: chapter.trim(),
    };

    const trimmedVS = verseStart.trim();
    const trimmedVE = verseEnd.trim();
    const trimmedT = translation.trim();

    if (trimmedVS) {
      args.verseStart = trimmedVS;
    }

    if (trimmedVE) {
      args.verseEnd = trimmedVE;
    }

    if (trimmedT) {
      args.translation = trimmedT;
    }

    setUrlSearchParams(args, { replace: true });

    await fetchVerses({
      book: book.trim(),
      chapter: Number(chapter),
      verseStart: verseStart.trim() ? Number(verseStart) : undefined,
      verseEnd: verseEnd.trim() ? Number(verseEnd) : undefined,
      translation: translation.trim() || "NIV",
    });
  }

  return (
    <VStack align="stretch" gap="6">
      <Heading size="lg">Verses</Heading>

      <form onSubmit={handleSubmit}>
        <Stack gap="4">
          <HStack gap="4" align="end" flexWrap="wrap">
            <Field.Root maxW="48">
              <Field.Label>Book</Field.Label>
              <Input
                placeholder='"Genesis" or "1"'
                value={book}
                onChange={(e) => setBook(e.target.value)}
                autoFocus
              />
            </Field.Root>

            <Field.Root maxW="28">
              <Field.Label>Chapter</Field.Label>
              <Input
                type="number"
                min={1}
                value={chapter}
                onChange={(e) => setChapter(e.target.value)}
              />
            </Field.Root>

            <Field.Root maxW="28">
              <Field.Label>Verse start</Field.Label>
              <Input
                type="number"
                min={1}
                placeholder="optional"
                value={verseStart}
                onChange={(e) => setVerseStart(e.target.value)}
              />
            </Field.Root>

            <Field.Root maxW="28">
              <Field.Label>Verse end</Field.Label>
              <Input
                type="number"
                min={1}
                placeholder="optional"
                value={verseEnd}
                onChange={(e) => setVerseEnd(e.target.value)}
              />
            </Field.Root>

            <Field.Root maxW="32">
              <Field.Label>Translation</Field.Label>
              <Input
                value={translation}
                onChange={(e) => setTranslation(e.target.value)}
              />
            </Field.Root>

            <Button type="submit" colorPalette="orange" loading={loading}>
              Fetch
            </Button>
          </HStack>
          <Text fontSize="sm" color="fg.muted">
            Leave verse start/end blank to fetch the whole chapter.
          </Text>
        </Stack>
      </form>

      <Separator />

      {error && (
        <Alert.Root status="error">
          <Alert.Indicator />
          <Alert.Title>{error}</Alert.Title>
        </Alert.Root>
      )}

      {loading && (
        <HStack justify="center" py="8">
          <Spinner />
        </HStack>
      )}

      {!loading && verses && verses.length === 0 && (
        <Text color="fg.muted">No verses found.</Text>
      )}

      {!loading && verses && verses.length > 0 && (
        <Stack gap="4">
          {readingBlocks ? (
            <ReadingView blocks={readingBlocks} />
          ) : (
            <Stack gap="1">
              {verses.map((verse) => (
                <Text key={`${verse.chapter}:${verse.verse}`}>
                  <Text as="sup" color="fg.subtle" fontSize="2xs" mr="0.5">
                    {verse.chapter}:{verse.verse}
                  </Text>
                  {verse.text}
                </Text>
              ))}
            </Stack>
          )}

          <ReferencesPanel
            key={`${pericopeId ?? ""}-${verses[0].book}-${verses[0].chapter}-${verses[0].verse}-${verses[verses.length - 1].chapter}-${verses[verses.length - 1].verse}`}
            translation={translation.trim() || "NIV"}
            pericopeId={pericopeId ?? undefined}
            initiallyOpen={pericopeId !== null}
            range={{
              book: verses[0].book,
              chapterStart: verses[0].chapter,
              verseStart: verses[0].verse,
              chapterEnd: verses[verses.length - 1].chapter,
              verseEnd: verses[verses.length - 1].verse,
            }}
          />
        </Stack>
      )}
    </VStack>
  );
}

export default VersesPage;
