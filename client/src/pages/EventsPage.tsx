import { useEffect, useState } from "react";

import {
  Alert,
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

import { ApiError, listEvents, type Event } from "@/lib/api";
import { EventDetailDialog } from "@/components/EventDetailDialog";
import fuzzysearch from "fuzzysearch-ts";

function EventsPage() {
  const [events, setEvents] = useState<Event[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    listEvents()
      .then(setEvents)
      .catch((err) =>
        setError(
          err instanceof ApiError
            ? err.message
            : "Something went wrong. Is the API running?",
        ),
      )
      .finally(() => setLoading(false));
  }, []);

  return (
    <VStack align="stretch" gap="6">
      <Heading size="lg">Events</Heading>

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

      {!loading && events && events.length > 0 && (
        <Box>
          <Box>
            <Input
              type="search"
              name="search"
              id="event-search"
              placeholder="Event Name"
              onChange={(e) => setSearch(e.target.value)}
            />
          </Box>
          <Table.Root variant="line" size="sm">
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeader>Title</Table.ColumnHeader>
                <Table.ColumnHeader>Start</Table.ColumnHeader>
                <Table.ColumnHeader>Duration</Table.ColumnHeader>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {events
                .filter(
                  (event) =>
                    !search ||
                    fuzzysearch(
                      search.toLowerCase(),
                      event.title.toLowerCase(),
                    ),
                )
                .map((event) => (
                  <Table.Row
                    key={event.id}
                    cursor="pointer"
                    _hover={{ bg: "bg.muted" }}
                    onClick={() => setSelectedId(event.id)}
                  >
                    <Table.Cell fontWeight="medium">{event.title}</Table.Cell>
                    <Table.Cell color="fg.muted">
                      {event.start_date ?? "—"}
                    </Table.Cell>
                    <Table.Cell color="fg.muted">
                      {event.duration ?? "—"}
                    </Table.Cell>
                  </Table.Row>
                ))}
            </Table.Body>
          </Table.Root>
        </Box>
      )}

      {!loading && events && events.length === 0 && (
        <Text color="fg.muted">No events found.</Text>
      )}

      <EventDetailDialog
        eventId={selectedId}
        onClose={() => setSelectedId(null)}
      />
    </VStack>
  );
}

export default EventsPage;
