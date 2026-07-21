import { Box, Heading, Stack, Text } from "@chakra-ui/react";
import type { HeadingBlock, ParagraphBlock, ReadingBlock, ReadingLine } from "@/lib/api";

function headingSize(level: number): "xl" | "lg" | "sm" {
  if (level <= 1) return "xl";
  if (level <= 2.5) return "lg";
  return "sm";
}

const INDENT_PADDING = ["0", "6", "12"];

// Tracks the chapter of the most recently rendered verse marker so a range
// spanning multiple chapters shows "3:1" on a chapter change and just "2"
// otherwise -- mutated in place across one top-to-bottom render pass of
// <ReadingView>, not persisted between renders or read outside of it.
type ChapterCursor = { chapter: number | null };

function Line({ line, cursor }: { line: ReadingLine; cursor: ChapterCursor }) {
  return (
    <Box pl={INDENT_PADDING[line.indent] ?? "0"} textAlign={line.align}>
      {line.runs.map((run, i) => {
        const showMarker = run.verse !== null && run.chapter !== null;
        const showChapter = showMarker && run.chapter !== cursor.chapter;
        if (showMarker) cursor.chapter = run.chapter;

        return (
          <Text as="span" key={i}>
            {showMarker && (
              <Text as="sup" color="fg.subtle" fontSize="2xs" mr="0.5">
                {showChapter ? `${run.chapter}:${run.verse}` : run.verse}
              </Text>
            )}
            <Text
              as="span"
              fontStyle={run.italic ? "italic" : undefined}
              fontWeight={run.bold ? "bold" : undefined}
              color={run.red_letter ? "red.fg" : undefined}
              style={run.smallcaps ? { fontVariant: "small-caps" } : undefined}
            >
              {run.text}
            </Text>{" "}
          </Text>
        );
      })}
    </Box>
  );
}

function Paragraph({ block, cursor }: { block: ParagraphBlock; cursor: ChapterCursor }) {
  return (
    <Stack gap="0.5">
      {block.lines.map((line, i) => (
        <Line key={i} line={line} cursor={cursor} />
      ))}
    </Stack>
  );
}

function HeadingBlockView({ block }: { block: HeadingBlock }) {
  return (
    <Heading size={headingSize(block.level)} color={block.level >= 3 ? "fg.muted" : undefined}>
      {block.text}
    </Heading>
  );
}

export function ReadingView({ blocks }: { blocks: ReadingBlock[] }) {
  const cursor: ChapterCursor = { chapter: null };

  return (
    <Stack gap="4" align="stretch">
      {blocks.map((block, i) =>
        block.kind === "heading" ? (
          <HeadingBlockView key={i} block={block} />
        ) : (
          <Paragraph key={i} block={block} cursor={cursor} />
        ),
      )}
    </Stack>
  );
}
