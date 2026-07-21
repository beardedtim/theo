import { useEffect, useState } from "react";
import { Alert, Badge, Dialog, HStack, Portal, Spinner, Stack, Text } from "@chakra-ui/react";
import { ApiError, getEvent, type EventDetail } from "@/lib/api";

export function EventDetailDialog({
  eventId,
  onClose,
}: {
  eventId: string | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!eventId) return;
    setDetail(null);
    setError(null);
    setLoading(true);
    getEvent(eventId)
      .then(setDetail)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load event."),
      )
      .finally(() => setLoading(false));
  }, [eventId]);

  return (
    <Dialog.Root open={eventId !== null} onOpenChange={(d) => !d.open && onClose()} size="md">
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content>
            <Dialog.Header>
              <Dialog.Title>{detail?.event.title ?? "Event"}</Dialog.Title>
            </Dialog.Header>
            <Dialog.Body pb="6">
              {loading && (
                <HStack justify="center" py="6">
                  <Spinner />
                </HStack>
              )}

              {error && (
                <Alert.Root status="error">
                  <Alert.Indicator />
                  <Alert.Title>{error}</Alert.Title>
                </Alert.Root>
              )}

              {detail && (
                <Stack gap="4">
                  {(detail.event.start_date || detail.event.duration) && (
                    <Text fontSize="sm" color="fg.muted">
                      {[detail.event.start_date, detail.event.duration]
                        .filter(Boolean)
                        .join(" · ")}
                    </Text>
                  )}

                  <Stack gap="1">
                    <Text fontSize="xs" color="fg.muted">
                      Participants
                    </Text>
                    {detail.participants.length === 0 ? (
                      <Text fontSize="sm" color="fg.muted">
                        None recorded.
                      </Text>
                    ) : (
                      <HStack gap="1.5" flexWrap="wrap">
                        {detail.participants.map((p) => (
                          <Badge key={p.id} colorPalette="blue" variant="subtle">
                            {p.display_title}
                          </Badge>
                        ))}
                      </HStack>
                    )}
                  </Stack>

                  <Stack gap="1">
                    <Text fontSize="xs" color="fg.muted">
                      Locations
                    </Text>
                    {detail.locations.length === 0 ? (
                      <Text fontSize="sm" color="fg.muted">
                        None recorded.
                      </Text>
                    ) : (
                      <HStack gap="1.5" flexWrap="wrap">
                        {detail.locations.map((l) => (
                          <Badge key={l.id} colorPalette="green" variant="subtle">
                            {l.display_title}
                          </Badge>
                        ))}
                      </HStack>
                    )}
                  </Stack>
                </Stack>
              )}
            </Dialog.Body>
            <Dialog.CloseTrigger />
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  );
}
