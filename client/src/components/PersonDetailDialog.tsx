import {
  Box,
  Dialog,
  HStack,
  Portal,
  Span,
  Stack,
  Text,
} from "@chakra-ui/react";
import { Prose } from "@/components/ui/prose";
import type { Person } from "@/lib/api";

function lifespan(person: Person): string | null {
  if (person.birth_year === null && person.death_year === null) return null;
  return `${person.birth_year ?? "?"}–${person.death_year ?? "?"}`;
}

export function PersonDetailDialog({
  person,
  onClose,
}: {
  person: Person | null;
  onClose: () => void;
}) {
  const alsoCalled = person?.also_called?.split(",") ?? [];
  return (
    <Dialog.Root
      open={person !== null}
      onOpenChange={(d) => !d.open && onClose()}
      size="md"
    >
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content>
            <Dialog.Header>
              <Dialog.Title>{person?.display_title}</Dialog.Title>
            </Dialog.Header>
            <Dialog.Body pb="6">
              {person && (
                <Stack gap="3">
                  <HStack gap="3" flexWrap="wrap">
                    {person.gender && (
                      <Box
                        display="flex"
                        alignItems="center"
                        fontSize="sm"
                        color="fg.muted"
                        gap={1}
                      >
                        <Text>Sex:</Text>
                        <Text>{person.gender}</Text>
                      </Box>
                    )}
                    {lifespan(person) && (
                      <Text fontSize="sm" color="fg.muted">
                        {lifespan(person)}
                      </Text>
                    )}
                  </HStack>

                  {person.also_called && (
                    <>
                      <Text fontSize="sm" color="fg.muted">
                        Also called:
                      </Text>
                      <Box
                        gap={1}
                        display="flex"
                        alignItems="center"
                        flexFlow="wrap"
                      >
                        {alsoCalled.map((name, i) => (
                          <Span
                            key={name.trim()}
                            fontStyle="italic"
                            fontSize="xs"
                          >
                            {name.trim()}
                            {i === alsoCalled.length - 1 ? "" : ","}
                          </Span>
                        ))}
                      </Box>
                    </>
                  )}

                  {person.dictionary_text ? (
                    <Box display="flex" flexDirection="column" gap={2}>
                      <Text>Dictionary:</Text>
                      <Prose
                        maxHeight="30vh"
                        overflowY="auto"
                        dangerouslySetInnerHTML={{
                          __html: person.dictionary_text,
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
