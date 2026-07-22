import { useEffect, useState } from "react";
import { useLocation } from "wouter";
import {
  Alert,
  Badge,
  Box,
  Heading,
  HStack,
  Input,
  Separator,
  Spinner,
  Table,
  Text,
  VStack,
} from "@chakra-ui/react";
import fuzzysearch from "fuzzysearch-ts";
import {
  ApiError,
  listNotes,
  listPassageGroups,
  type Note,
  type PassageGroup,
} from "@/lib/api";
import { noteHref, noteRangeLabel } from "@/lib/notes";

function NoteScope({
  note,
  groupsById,
}: {
  note: Note;
  groupsById: Map<string, PassageGroup>;
}) {
  if (note.passage_group_id) {
    return (
      <Badge colorPalette="purple" variant="subtle">
        {groupsById.get(note.passage_group_id)?.name ?? "Passage group"}
      </Badge>
    );
  }
  return (
    <Text fontSize="sm" color="fg.muted">
      {noteRangeLabel(note)}
    </Text>
  );
}

function NotesPage() {
  const [, navigate] = useLocation();

  const [notes, setNotes] = useState<Note[] | null>(null);
  const [groups, setGroups] = useState<PassageGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    Promise.all([listNotes(), listPassageGroups()])
      .then(([fetchedNotes, fetchedGroups]) => {
        setNotes(fetchedNotes);
        setGroups(fetchedGroups);
      })
      .catch((err) =>
        setError(
          err instanceof ApiError
            ? err.message
            : "Something went wrong. Is the API running?",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  const groupsById = new Map(groups.map((g) => [g.id, g]));

  return (
    <VStack align="stretch" gap="6">
      <Heading size="lg">Notes</Heading>
      <Text fontSize="sm" color="fg.muted">
        Personal commentary anchored to a passage or a whole group of books
        (e.g. Pentateuch authorship), supplementing the reference data with your
        own research.
      </Text>

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

      {!loading && notes && notes.length > 0 && (
        <Box>
          <Box mb="3">
            <Input
              type="search"
              name="search"
              id="note-search"
              placeholder="Note title"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </Box>
          <Table.Root variant="line" size="sm">
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeader>Title</Table.ColumnHeader>
                <Table.ColumnHeader>Passage</Table.ColumnHeader>
                <Table.ColumnHeader>Tags</Table.ColumnHeader>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {notes
                .filter(
                  (note) =>
                    !search ||
                    fuzzysearch(
                      search.toLowerCase(),
                      note.title.toLowerCase(),
                    ) ||
                    fuzzysearch(
                      search.toLowerCase(),
                      note.slug.toLowerCase(),
                    ) ||
                    note.tags.some((tag) =>
                      fuzzysearch(search.toLowerCase(), tag.toLowerCase()),
                    ),
                )
                .map((note) => (
                  <Table.Row
                    key={note.id}
                    cursor="pointer"
                    _hover={{ bg: "bg.muted" }}
                    onClick={() => navigate(noteHref(note.slug))}
                  >
                    <Table.Cell fontWeight="medium">{note.title}</Table.Cell>
                    <Table.Cell>
                      <NoteScope note={note} groupsById={groupsById} />
                    </Table.Cell>
                    <Table.Cell>
                      <HStack gap="1" flexWrap="wrap">
                        {note.tags.map((tag) => (
                          <Badge
                            key={tag}
                            colorPalette="gray"
                            variant="outline"
                          >
                            {tag}
                          </Badge>
                        ))}
                      </HStack>
                    </Table.Cell>
                  </Table.Row>
                ))}
            </Table.Body>
          </Table.Root>
        </Box>
      )}

      {!loading && notes && notes.length === 0 && (
        <Text color="fg.muted">No notes found.</Text>
      )}
    </VStack>
  );
}

export default NotesPage;
