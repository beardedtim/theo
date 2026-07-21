import { useState, type SubmitEvent } from "react";
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
  getLexiconEntries,
  searchLexicon,
  type LexiconEntry,
} from "@/lib/api";
import { LexiconEntryCard } from "@/components/LexiconEntryCard";

/**
 * A query like "H175", "g2424", or "H2148w" is a Strong's number: normalize it
 * to the stored form (uppercase H/G, digits zero-padded to 4 — suffix letter
 * kept as typed since lowercase disambiguators like H2148w are distinct codes).
 * Anything else is a word search.
 */
function normalizeStrongs(q: string): string | null {
  const match = /^([hg])\s*(\d{1,5})([a-z]?)$/i.exec(q);
  if (!match) return null;
  return `${match[1].toUpperCase()}${match[2].padStart(4, "0")}${match[3]}`;
}

function LexiconPage() {
  const [q, setQ] = useState("");

  const [entries, setEntries] = useState<LexiconEntry[] | null>(null);
  const [lookedUp, setLookedUp] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    const query = q.trim();
    if (!query) return;

    const strongs = normalizeStrongs(query);

    setLoading(true);
    setError(null);
    setLookedUp(strongs);
    try {
      const data = strongs
        ? await getLexiconEntries(strongs)
        : await searchLexicon(query, 50);
      setEntries(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setEntries([]);
      } else {
        setEntries(null);
        setError(err instanceof ApiError ? err.message : "Something went wrong. Is the API running?");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <VStack align="stretch" gap="6">
      <Heading size="lg">Lexicon</Heading>

      <form onSubmit={handleSubmit}>
        <HStack gap="4" align="end" flexWrap="wrap">
          <Field.Root maxW="md">
            <Field.Label>Word or Strong's number</Field.Label>
            <Input
              placeholder='e.g. "steadfast love" or "H0175"'
              value={q}
              onChange={(e) => setQ(e.target.value)}
              autoFocus
            />
          </Field.Root>

          <Button type="submit" colorPalette="orange" loading={loading}>
            Look up
          </Button>
        </HStack>
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

      {!loading && entries && entries.length === 0 && (
        <Text color="fg.muted">
          {lookedUp
            ? `No lexicon entries for ${lookedUp}.`
            : "No lexicon entries matched."}
        </Text>
      )}

      {!loading && entries && entries.length > 0 && (
        <Stack gap="3">
          <Text fontSize="sm" color="fg.muted">
            {lookedUp
              ? `${entries.length} entr${entries.length === 1 ? "y" : "ies"} for ${lookedUp}`
              : `${entries.length} match${entries.length === 1 ? "" : "es"}`}
          </Text>
          {entries.map((entry) => (
            <LexiconEntryCard key={entry.dstrong} entry={entry} />
          ))}
        </Stack>
      )}
    </VStack>
  );
}

export default LexiconPage;
