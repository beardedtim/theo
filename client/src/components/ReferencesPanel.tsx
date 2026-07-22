import { useEffect, useState, type ReactNode } from "react";
import { Link } from "wouter";
import {
  Badge,
  Box,
  Button,
  Collapsible,
  HStack,
  Stack,
  Text,
} from "@chakra-ui/react";
import { Tooltip } from "@/components/ui/tooltip";
import { EventDetailDialog } from "@/components/EventDetailDialog";
import { NameDetailDialog } from "@/components/NameDetailDialog";
import { PersonDetailDialog } from "@/components/PersonDetailDialog";
import { PlaceDetailDialog } from "@/components/PlaceDetailDialog";
import {
  ApiError,
  getMetadataForPericope,
  getMetadataForRange,
  type Event,
  type EntityKind,
  type MetadataEntity,
  type Note,
  type Person,
  type Place,
  type StepName,
  type VerseMetadata,
  type VerseRangeParams,
} from "@/lib/api";
import { noteHref } from "@/lib/notes";

const KIND_ROWS: { kind: EntityKind; label: string; color: string }[] = [
  { kind: "person", label: "People", color: "blue" },
  { kind: "place", label: "Places", color: "green" },
  { kind: "group", label: "Groups", color: "orange" },
  { kind: "other", label: "Other", color: "teal" },
];

function EntityBadge({
  entity,
  color,
  onClick,
}: {
  entity: MetadataEntity;
  color: string;
  onClick?: () => void;
}) {
  return (
    <Tooltip
      content={entity.description ?? entity.name}
      contentProps={{ maxW: "sm" }}
    >
      <Badge
        colorPalette={color}
        variant="subtle"
        cursor={onClick ? "pointer" : undefined}
        onClick={onClick}
      >
        {entity.name}
      </Badge>
    </Tooltip>
  );
}

function EventBadge({ event, onClick }: { event: Event; onClick: () => void }) {
  return (
    <Tooltip
      content={event.start_date ?? event.title}
      contentProps={{ maxW: "sm" }}
    >
      <Badge
        colorPalette="orange"
        variant="subtle"
        cursor="pointer"
        onClick={onClick}
      >
        {event.title}
      </Badge>
    </Tooltip>
  );
}

function ReferenceRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <HStack gap="2" flexWrap="wrap" align="start">
      <Text fontSize="xs" color="fg.muted" minW="14" pt="0.5">
        {label}
      </Text>
      <HStack gap="1.5" flexWrap="wrap">
        {children}
      </HStack>
    </HStack>
  );
}

function NoteBadge({ note }: { note: Note }) {
  const snippet = note.body.split(/\n\s*\n/)[0]?.slice(0, 200) ?? note.title;
  return (
    <Tooltip content={snippet} contentProps={{ maxW: "sm" }}>
      <Link href={noteHref(note.slug)}>
        <Badge colorPalette="purple" variant="subtle" cursor="pointer">
          {note.title}
        </Badge>
      </Link>
    </Tooltip>
  );
}

/** Facts (author, date, ...) inherited from personal notes -- either
 * anchored directly to this range or to a passage group the book belongs
 * to (e.g. a Pentateuch-wide authorship note applying to Genesis). See
 * theo.metadata.resolve_attributes. Rendered as its own callout, above the
 * reference badges, since these are usually the first thing worth reading
 * about a passage rather than a supporting detail. */
function AttributesPanel({ metadata }: { metadata: VerseMetadata }) {
  const entries = Object.entries(metadata.attributes);
  if (entries.length === 0) return null;

  const groupName = (slug: string) =>
    metadata.passage_groups.find((g) => g.slug === slug)?.name ?? slug;

  return (
    <Stack
      gap="3"
      p="3"
      borderWidth="1px"
      borderColor="border.muted"
      borderRadius="md"
      bg="bg.subtle"
    >
      {entries.map(([key, attribute]) => (
        <Box key={key}>
          <HStack gap="2" align="baseline" flexWrap="wrap" textAlign="left">
            <Text
              fontSize="xs"
              fontWeight="semibold"
              textTransform="uppercase"
              color="fg.muted"
            >
              {key}
            </Text>
            <Link href={noteHref(attribute.source_note_slug)}>
              <Text
                as="span"
                fontSize="2xs"
                color="fg.subtle"
                textDecoration="underline"
                textUnderlineOffset="2px"
                cursor="pointer"
              >
                via note
                {attribute.scope !== "range"
                  ? ` on ${groupName(attribute.scope)}`
                  : ""}
              </Text>
            </Link>
          </HStack>
          <Text fontSize="xs">{attribute.value}</Text>
        </Box>
      ))}
    </Stack>
  );
}

/** The subject–verb–object statements the NLP pipeline extracted from the
 * passage's coref-resolved text, one annotation per pericope the range
 * overlaps (the server already picked each pericope's best pipeline). */
function StatementsRow({ metadata }: { metadata: VerseMetadata }) {
  const triples = metadata.annotations.flatMap((a) => a.svo);
  if (triples.length === 0) return null;
  return (
    <HStack gap="2" align="start">
      <Text fontSize="xs" color="fg.muted" minW="14" pt="0.5">
        Statements
      </Text>
      <Box maxH="40" overflowY="auto" flex="1">
        <Stack gap="0.5">
          {triples.map(([subject, verb, object], i) => (
            <Text key={i} fontSize="sm">
              <Text as="span" fontWeight="medium">
                {subject}
              </Text>
              <Text as="span" color="fg.muted">
                {" "}
                {verb}{" "}
              </Text>
              <Text as="span" fontWeight="medium">
                {object}
              </Text>
            </Text>
          ))}
        </Stack>
      </Box>
    </HStack>
  );
}

/**
 * Everything the database knows about a passage, loaded lazily with a single
 * /metadata call when the panel is first opened. Pass `pericopeId` when the
 * passage is a pericope (e.g. a search result) so the server resolves its
 * stored range; otherwise the manual verse range is used.
 */
export function ReferencesPanel({
  range,
  pericopeId,
  translation,
  initiallyOpen,
}: {
  range: VerseRangeParams;
  pericopeId?: string;
  translation?: string;
  /** Expand and load details immediately, e.g. when arriving via a "Read in context" link. */
  initiallyOpen?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [metadata, setMetadata] = useState<VerseMetadata | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
  const [selectedPlace, setSelectedPlace] = useState<Place | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState<StepName | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setMetadata(
        pericopeId
          ? await getMetadataForPericope(pericopeId, translation)
          : await getMetadataForRange(range, translation),
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't load passage details.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleToggle() {
    const next = !open;
    setOpen(next);
    if (next && metadata === null && !loading) {
      await load();
    }
  }

  useEffect(() => {
    if (initiallyOpen) {
      setOpen(true);
      void load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function entityClickHandler(
    entity: MetadataEntity,
  ): (() => void) | undefined {
    if (entity.source === "step") return () => setSelectedName(entity.data);
    if (entity.kind === "person") return () => setSelectedPerson(entity.data);
    if (entity.kind === "place") return () => setSelectedPlace(entity.data);
    return undefined; // theographic groups have no detail view
  }

  const total = metadata
    ? metadata.entities.length + metadata.events.length + metadata.notes.length
    : null;
  const hasAttributes = metadata
    ? Object.keys(metadata.attributes).length > 0
    : false;

  return (
    <Stack gap="2">
      <Button
        size="xs"
        variant="ghost"
        alignSelf="start"
        onClick={handleToggle}
        loading={loading}
      >
        {open ? "Hide" : "Show"} passage details
        {total !== null ? ` (${total})` : ""}
      </Button>

      <Collapsible.Root open={open}>
        <Collapsible.Content>
          <Stack gap="2" pt="1">
            {error && (
              <Text fontSize="sm" color="red.fg">
                {error}
              </Text>
            )}

            {metadata &&
              total === 0 &&
              metadata.annotations.length === 0 &&
              !hasAttributes && (
                <Text fontSize="sm" color="fg.muted">
                  Nothing found for this passage.
                </Text>
              )}

            {metadata && <AttributesPanel metadata={metadata} />}

            {metadata && metadata.notes.length > 0 && (
              <ReferenceRow label="Notes">
                {metadata.notes.map((note) => (
                  <NoteBadge key={note.id} note={note} />
                ))}
              </ReferenceRow>
            )}

            {metadata &&
              KIND_ROWS.map(({ kind, label, color }) => {
                const entities = metadata.entities.filter(
                  (e) => e.kind === kind,
                );
                if (entities.length === 0) return null;
                return (
                  <ReferenceRow key={kind} label={label}>
                    {entities.map((entity, i) => (
                      <EntityBadge
                        key={`${entity.source}-${i}`}
                        entity={entity}
                        color={color}
                        onClick={entityClickHandler(entity)}
                      />
                    ))}
                  </ReferenceRow>
                );
              })}

            {metadata && metadata.events.length > 0 && (
              <ReferenceRow label="Events">
                {metadata.events.map((e) => (
                  <EventBadge
                    key={e.id}
                    event={e}
                    onClick={() => setSelectedEventId(e.id)}
                  />
                ))}
              </ReferenceRow>
            )}

            {metadata && <StatementsRow metadata={metadata} />}
          </Stack>
        </Collapsible.Content>
      </Collapsible.Root>

      <PersonDetailDialog
        person={selectedPerson}
        onClose={() => setSelectedPerson(null)}
      />
      <PlaceDetailDialog
        place={selectedPlace}
        onClose={() => setSelectedPlace(null)}
      />
      <EventDetailDialog
        eventId={selectedEventId}
        onClose={() => setSelectedEventId(null)}
      />
      <NameDetailDialog
        name={selectedName}
        lexicon={
          selectedName ? (metadata?.lexicon[selectedName.ustrong] ?? []) : []
        }
        onClose={() => setSelectedName(null)}
      />
    </Stack>
  );
}
