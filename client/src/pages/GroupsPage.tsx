import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Box,
  Dialog,
  HStack,
  Heading,
  Input,
  Portal,
  Separator,
  Spinner,
  Stack,
  Table,
  Text,
  VStack,
} from "@chakra-ui/react";
import {
  ApiError,
  getPeopleGroup,
  listPeopleGroups,
  type GroupDetail,
  type PeopleGroup,
} from "@/lib/api";
import fuzzysearch from "fuzzysearch-ts";

function GroupDetailDialog({
  groupId,
  onClose,
}: {
  groupId: string | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!groupId) return;
    setDetail(null);
    setError(null);
    setLoading(true);
    getPeopleGroup(groupId)
      .then(setDetail)
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : "Couldn't load group.",
        ),
      )
      .finally(() => setLoading(false));
  }, [groupId]);

  return (
    <Dialog.Root
      open={groupId !== null}
      onOpenChange={(d) => !d.open && onClose()}
      size="md"
    >
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content>
            <Dialog.Header>
              <Dialog.Title>{detail?.group.group_name ?? "Group"}</Dialog.Title>
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
                <Stack gap="1">
                  <Text fontSize="xs" color="fg.muted">
                    Members
                  </Text>
                  {detail.members.length === 0 ? (
                    <Text fontSize="sm" color="fg.muted">
                      None recorded.
                    </Text>
                  ) : (
                    <HStack gap="1.5" flexWrap="wrap">
                      {detail.members.map((p) => (
                        <Badge key={p.id} colorPalette="blue" variant="subtle">
                          {p.display_title}
                        </Badge>
                      ))}
                    </HStack>
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

function GroupsPage() {
  const [groups, setGroups] = useState<PeopleGroup[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    listPeopleGroups()
      .then(setGroups)
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
      <Heading size="lg">People Groups</Heading>

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

      {!loading && groups && groups.length > 0 && (
        <Box>
          <Box>
            <Input
              type="search"
              name="search"
              id="groups-search"
              placeholder="Group Name"
              onChange={(e) => setSearch(e.target.value)}
            />
          </Box>
          <Table.Root variant="line" size="sm">
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeader>Name</Table.ColumnHeader>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {groups
                .filter(
                  (group) =>
                    !search ||
                    fuzzysearch(
                      search.toLowerCase(),
                      group.group_name.toLowerCase(),
                    ),
                )
                .map((group) => (
                  <Table.Row
                    key={group.id}
                    cursor="pointer"
                    _hover={{ bg: "bg.muted" }}
                    onClick={() => setSelectedId(group.id)}
                  >
                    <Table.Cell fontWeight="medium">
                      {group.group_name}
                    </Table.Cell>
                  </Table.Row>
                ))}
            </Table.Body>
          </Table.Root>
        </Box>
      )}

      {!loading && groups && groups.length === 0 && (
        <Text color="fg.muted">No people groups found.</Text>
      )}

      <GroupDetailDialog
        groupId={selectedId}
        onClose={() => setSelectedId(null)}
      />
    </VStack>
  );
}

export default GroupsPage;
