import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Box,
  Dialog,
  HStack,
  Portal,
  Spinner,
  Stack,
  Table,
  Text,
} from "@chakra-ui/react";
import { Prose } from "@/components/ui/prose";
import { LexiconEntryCard } from "@/components/LexiconEntryCard";
import {
  ApiError,
  getStepName,
  type LexiconEntry,
  type StepName,
  type StepNameDetail,
} from "@/lib/api";

const CATEGORY_COLORS: Record<StepName["category"], string> = {
  person: "blue",
  place: "green",
  other: "gray",
};

/** "Ebron =ESV; Abdon =NIV; Hebron =KJV" -> "Ebron (ESV), Abdon (NIV), Hebron (KJV)" */
function renderTranslations(raw: string): string {
  return raw
    .split(";")
    .map((segment) => {
      const [name, version] = segment.split("=").map((s) => s.trim());
      return version ? `${name} (${version})` : name;
    })
    .join(", ");
}

function FamilyRow({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <HStack gap="2" align="start">
      <Text fontSize="xs" color="fg.muted" minW="16">
        {label}
      </Text>
      <Text fontSize="sm">{value}</Text>
    </HStack>
  );
}

/**
 * Detail dialog for a TIPNR proper noun: the summary data arrives with the
 * passage metadata (name + its Strong's lexicon entries); the fuller record
 * (name forms, prose article, family) is fetched from /name/{id} on open.
 */
export function NameDetailDialog({
  name,
  lexicon,
  onClose,
}: {
  name: StepName | null;
  lexicon: LexiconEntry[];
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<StepNameDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!name) return;
    setDetail(null);
    setError(null);
    setLoading(true);
    getStepName(name.id)
      .then(setDetail)
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Couldn't load name details."),
      )
      .finally(() => setLoading(false));
  }, [name]);

  return (
    <Dialog.Root open={name !== null} onOpenChange={(d) => !d.open && onClose()} size="lg">
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content>
            <Dialog.Header>
              <HStack gap="2">
                <Dialog.Title>{name?.name}</Dialog.Title>
                {name && (
                  <Badge colorPalette={CATEGORY_COLORS[name.category]} variant="subtle">
                    {name.entity_type ?? name.category}
                  </Badge>
                )}
                {name && <Badge variant="outline">{name.ustrong}</Badge>}
              </HStack>
            </Dialog.Header>
            <Dialog.Body pb="6">
              <Stack gap="4">
                {name?.description && <Text fontSize="sm">{name.description}</Text>}

                {loading && (
                  <HStack justify="center" py="4">
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
                  <>
                    {(detail.parents || detail.partners || detail.offspring || detail.tribe) && (
                      <Stack gap="1">
                        <FamilyRow label="Parents" value={detail.parents} />
                        <FamilyRow label="Siblings" value={detail.siblings} />
                        <FamilyRow label="Partners" value={detail.partners} />
                        <FamilyRow label="Offspring" value={detail.offspring} />
                        <FamilyRow label="Tribe" value={detail.tribe} />
                      </Stack>
                    )}

                    {detail.forms.length > 0 && (
                      <Stack gap="1">
                        <Text fontSize="xs" color="fg.muted">
                          Name forms
                        </Text>
                        <Table.ScrollArea maxH="30vh">
                          <Table.Root size="sm">
                            <Table.Body>
                              {detail.forms.map((form, i) => (
                                <Table.Row key={i}>
                                  <Table.Cell>
                                    <Text fontSize="sm">{form.original ?? "—"}</Text>
                                  </Table.Cell>
                                  <Table.Cell>
                                    <Badge variant="outline" size="sm">
                                      {form.dstrong ?? form.significance}
                                    </Badge>
                                  </Table.Cell>
                                  <Table.Cell>
                                    <Text fontSize="xs" color="fg.muted">
                                      {form.translations ? renderTranslations(form.translations) : form.significance}
                                    </Text>
                                  </Table.Cell>
                                </Table.Row>
                              ))}
                            </Table.Body>
                          </Table.Root>
                        </Table.ScrollArea>
                      </Stack>
                    )}

                    <Text fontSize="xs" color="fg.muted">
                      Mentioned in {detail.refs.length} verse{detail.refs.length === 1 ? "" : "s"}
                    </Text>

                    {detail.article_html && (
                      <Box>
                        <Text fontSize="xs" color="fg.muted" mb="1">
                          About
                        </Text>
                        <Prose
                          fontSize="sm"
                          maxHeight="30vh"
                          overflowY="auto"
                          dangerouslySetInnerHTML={{ __html: detail.article_html }}
                        />
                      </Box>
                    )}
                  </>
                )}

                {lexicon.length > 0 && (
                  <Stack gap="2">
                    <Text fontSize="xs" color="fg.muted">
                      Lexicon
                    </Text>
                    {lexicon.map((entry) => (
                      <LexiconEntryCard key={entry.dstrong} entry={entry} />
                    ))}
                  </Stack>
                )}
              </Stack>
            </Dialog.Body>
            <Dialog.CloseTrigger />
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  );
}
