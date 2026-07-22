import { useEffect, useState } from "react";
import { Link, useParams } from "wouter";
import {
  Alert,
  Badge,
  Box,
  HStack,
  Heading,
  Separator,
  Spinner,
  Stack,
  Text,
  VStack,
} from "@chakra-ui/react";
import { LuArrowLeft } from "react-icons/lu";
import { Prose } from "@/components/ui/prose";
import {
  ApiError,
  getNote,
  listPassageGroups,
  type Note,
  type PassageGroup,
} from "@/lib/api";
import { noteParagraphs, noteRangeLabel } from "@/lib/notes";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function NoteScope({ note, groups }: { note: Note; groups: PassageGroup[] }) {
  if (note.passage_group_id) {
    const group = groups.find((g) => g.id === note.passage_group_id);
    return (
      <Badge colorPalette="purple" variant="subtle">
        {group?.name ?? "Passage group"}
      </Badge>
    );
  }
  const range = noteRangeLabel(note);
  return range ? (
    <Text fontSize="sm" color="fg.muted">
      {range}
    </Text>
  ) : null;
}

function NoteDetailPage() {
  const params = useParams<{ "*": string }>();
  const slug = params["*"] ?? "";

  const [note, setNote] = useState<Note | null>(null);
  const [groups, setGroups] = useState<PassageGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setNote(null);
    setError(null);
    setLoading(true);
    Promise.all([getNote(slug), listPassageGroups()])
      .then(([fetchedNote, fetchedGroups]) => {
        setNote(fetchedNote);
        setGroups(fetchedGroups);
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load note."),
      )
      .finally(() => setLoading(false));
  }, [slug]);

  return (
    <VStack align="stretch" gap="6">
      <Link href="/notes">
        <HStack
          gap="1.5"
          color="fg.muted"
          cursor="pointer"
          _hover={{ color: "fg" }}
          width="fit-content"
        >
          <LuArrowLeft />
          <Text fontSize="sm">All notes</Text>
        </HStack>
      </Link>

      {loading && (
        <HStack justify="center" py="8">
          <Spinner />
        </HStack>
      )}

      {error && (
        <Alert.Root status="error">
          <Alert.Indicator />
          <Alert.Title>{error}</Alert.Title>
        </Alert.Root>
      )}

      {note && (
        <VStack align="stretch" gap="5">
          <VStack align="start" gap="2">
            <Heading size="lg">{note.title}</Heading>
            <HStack gap="2" flexWrap="wrap">
              <NoteScope note={note} groups={groups} />
              {note.tags.map((tag) => (
                <Badge key={tag} colorPalette="gray" variant="outline">
                  {tag}
                </Badge>
              ))}
            </HStack>
          </VStack>

          <Separator />

          {Object.keys(note.attributes).length > 0 && (
            <Stack
              gap="10"
              p="3"
              borderWidth="1px"
              borderColor="border.muted"
              borderRadius="md"
              bg="bg.subtle"
            >
              {Object.entries(note.attributes).map(([key, value]) => (
                <Box key={key} textAlign="left" display="flex">
                  <Text
                    fontSize="xs"
                    fontWeight="semibold"
                    textTransform="uppercase"
                    color="fg.muted"
                    marginBottom="1.5"
                  >
                    {key}
                  </Text>
                  <Text fontSize="xs" paddingLeft="1.5">
                    {value}
                  </Text>
                </Box>
              ))}
            </Stack>
          )}

          <Prose
            maxWidth="55rem"
            width="98%"
            margin="0 auto"
            textAlign="left"
            css={{
              "& p": {
                "margin-bottom": "1rem",
              },
              "& h1, & h2, & h3, & h4, & h5, & h6": {
                marginBottom: "2rem",
                marginTop: "2rem",
              },
            }}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {note.body}
            </ReactMarkdown>
          </Prose>
        </VStack>
      )}
    </VStack>
  );
}

export default NoteDetailPage;
