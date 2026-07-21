import { Box, Dialog, HStack, Portal, Stack, Text } from "@chakra-ui/react";
import { Prose } from "@/components/ui/prose";
import type { Place } from "@/lib/api";

export function PlaceDetailDialog({
  place,
  onClose,
}: {
  place: Place | null;
  onClose: () => void;
}) {
  return (
    <Dialog.Root
      open={place !== null}
      onOpenChange={(d) => !d.open && onClose()}
      size="md"
    >
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content>
            <Dialog.Header>
              <Dialog.Title>{place?.display_title}</Dialog.Title>
            </Dialog.Header>
            <Dialog.Body pb="6">
              {place && (
                <Stack gap="3">
                  <HStack gap="3" flexWrap="wrap">
                    {place.feature_type && (
                      <Text fontSize="sm" color="fg.muted">
                        {[place.feature_type, place.feature_sub_type]
                          .filter(Boolean)
                          .join(" · ")}
                      </Text>
                    )}
                    {place.latitude !== null && place.longitude !== null && (
                      <Text fontSize="sm" color="fg.muted">
                        {place.latitude.toFixed(4)},{" "}
                        {place.longitude.toFixed(4)}
                      </Text>
                    )}
                  </HStack>

                  {place.dictionary_text ? (
                    <Box display="flex" flexDirection="column" gap={2}>
                      <Text>Dictionary:</Text>
                      <Prose
                        maxHeight="30vh"
                        overflowY="auto"
                        dangerouslySetInnerHTML={{
                          __html: place.dictionary_text,
                        }}
                      />
                    </Box>
                  ) : (
                    <Text fontSize="sm" color="fg.muted">
                      No dictionary entry available.
                    </Text>
                  )}
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
