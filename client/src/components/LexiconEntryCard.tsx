import { Badge, HStack, Stack, Text } from "@chakra-ui/react";
import { Prose } from "@/components/ui/prose";
import { type LexiconEntry } from "@/lib/api";

export function LexiconEntryCard({ entry }: { entry: LexiconEntry }) {
  return (
    <Stack gap="1" borderWidth="1px" borderColor="border" borderRadius="md" p="2">
      <HStack gap="2" flexWrap="wrap">
        <Text fontWeight="semibold" fontSize="lg" lang={entry.language === "hebrew" ? "he" : "el"}>
          {entry.original}
        </Text>
        {entry.transliteration && (
          <Text fontStyle="italic" color="fg.muted">
            {entry.transliteration}
          </Text>
        )}
        <Badge variant="outline">{entry.dstrong}</Badge>
        {entry.morph && <Badge variant="outline">{entry.morph}</Badge>}
        {entry.relation && (
          <Text fontSize="xs" color="fg.muted">
            {entry.relation} {entry.ustrong}
          </Text>
        )}
      </HStack>
      {entry.gloss && <Text fontSize="sm">“{entry.gloss}”</Text>}
      {entry.meaning_html && (
        <Prose
          fontSize="sm"
          maxHeight="20vh"
          overflowY="auto"
          dangerouslySetInnerHTML={{ __html: entry.meaning_html }}
        />
      )}
    </Stack>
  );
}
