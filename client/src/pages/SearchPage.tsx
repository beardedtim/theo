import { useState, type SubmitEvent } from "react";
import {
  Alert,
  Badge,
  Card,
  Field,
  Heading,
  HStack,
  Icon,
  Input,
  NativeSelect,
  Separator,
  Spinner,
  Stack,
  Text,
  VStack,
  Button,
} from "@chakra-ui/react";
import { Link } from "wouter";
import { LuBookOpen } from "react-icons/lu";
import {
  ApiError,
  search,
  type SearchMode,
  type SearchResult,
} from "@/lib/api";
import { ReferencesPanel } from "@/components/ReferencesPanel";

const MODES: { value: SearchMode; label: string }[] = [
  { value: "hybrid", label: "Hybrid (semantic + bm25)" },
  { value: "semantic", label: "Semantic" },
  { value: "bm25", label: "BM25 (keyword)" },
];

function reference(result: SearchResult): string {
  const { verses } = result;
  if (verses.length === 0) return result.pericope.title;

  const first = verses[0];
  const last = verses[verses.length - 1];
  const book = first.book;
  if (first.chapter === last.chapter) {
    return first.verse === last.verse
      ? `${book} ${first.chapter}:${first.verse}`
      : `${book} ${first.chapter}:${first.verse}-${last.verse}`;
  }
  return `${book} ${first.chapter}:${first.verse}-${last.chapter}:${last.verse}`;
}

// Pericopes never span more than one chapter in the data, so the pericope's
// own chapter_start/chapter_end double as a single chapter for /verses.
function versesHref(result: SearchResult, translation: string): string {
  const { pericope, verses } = result;
  const params = new URLSearchParams({
    book: verses[0]?.book ?? String(pericope.book),
    chapter: String(pericope.chapter_start),
    verseStart: String(pericope.verse_start),
    verseEnd: String(pericope.verse_end),
    translation,
    pericopeId: pericope.id,
  });
  return `/verses?${params.toString()}`;
}

function SearchResultCard({ result, translation }: { result: SearchResult; translation: string }) {
  return (
    <Card.Root>
      <Card.Header>
        <HStack justify="space-between" align="start">
          <Stack gap="0.5">
            <Card.Title>{result.pericope.title}</Card.Title>
            <Text fontSize="sm" color="fg.muted">
              {reference(result)}
            </Text>
          </Stack>
          <Badge colorPalette="orange" variant="subtle">
            score {result.score.toFixed(3)}
          </Badge>
        </HStack>
      </Card.Header>
      <Card.Body pt="0">
        <Stack gap="3">
          <Text>
            {result.verses.map((verse) => (
              <Text as="span" key={verse.verse}>
                <Text as="sup" color="fg.subtle" fontSize="2xs" mr="0.5">
                  {verse.verse}
                </Text>
                {verse.text}{" "}
              </Text>
            ))}
          </Text>

          <Button asChild size="xs" variant="outline" colorPalette="orange" alignSelf="start">
            <Link href={versesHref(result, translation)}>
              <Icon as={LuBookOpen} />
              Read in context
            </Link>
          </Button>

          <ReferencesPanel
            pericopeId={result.pericope.id}
            translation={translation}
            range={{
              book: result.pericope.book,
              chapterStart: result.pericope.chapter_start,
              verseStart: result.pericope.verse_start,
              chapterEnd: result.pericope.chapter_end,
              verseEnd: result.pericope.verse_end,
            }}
          />
        </Stack>
      </Card.Body>
    </Card.Root>
  );
}

function SearchPage() {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [limit, setLimit] = useState("10");
  const [translation, setTranslation] = useState("NIV");

  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!q.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const data = await search({
        q: q.trim(),
        mode,
        limit: Number(limit) || 10,
        translation: translation.trim() || "NIV",
      });
      setResults(data);
    } catch (err) {
      setResults(null);
      setError(err instanceof ApiError ? err.message : "Something went wrong. Is the API running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <VStack align="stretch" gap="6">
      <Heading size="lg">Search</Heading>

      <form onSubmit={handleSubmit}>
        <Stack gap="4">
          <Field.Root>
            <Field.Label>Query</Field.Label>
            <Input
              placeholder='e.g. "a shepherd caring for lost sheep"'
              value={q}
              onChange={(e) => setQ(e.target.value)}
              autoFocus
            />
          </Field.Root>

          <HStack gap="4" align="end" flexWrap="wrap">
            <Field.Root maxW="56">
              <Field.Label>Mode</Field.Label>
              <NativeSelect.Root>
                <NativeSelect.Field
                  value={mode}
                  onChange={(e) => setMode(e.target.value as SearchMode)}
                >
                  {MODES.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </NativeSelect.Field>
                <NativeSelect.Indicator />
              </NativeSelect.Root>
            </Field.Root>

            <Field.Root maxW="28">
              <Field.Label>Limit</Field.Label>
              <Input
                type="number"
                min={1}
                max={50}
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
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
              Search
            </Button>
          </HStack>
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

      {!loading && results && results.length === 0 && (
        <Text color="fg.muted">No results found.</Text>
      )}

      {!loading && results && results.length > 0 && (
        <Stack gap="4">
          {results.map((result) => (
            <SearchResultCard
              key={result.pericope.id}
              result={result}
              translation={translation.trim() || "NIV"}
            />
          ))}
        </Stack>
      )}
    </VStack>
  );
}

export default SearchPage;
