import {
  Badge,
  Box,
  Button,
  Heading,
  HStack,
  Icon,
  SimpleGrid,
  Text,
  VStack,
} from "@chakra-ui/react";
import { Link } from "wouter";
import type { IconType } from "react-icons";
import {
  LuArrowRight,
  LuBookOpen,
  LuLanguages,
  LuMessageCircleQuestion,
  LuNetwork,
  LuNotebookPen,
  LuSearch,
  LuSparkles,
} from "react-icons/lu";

const STATS: { value: string; label: string }[] = [
  { value: "3,000+", label: "Biblical people" },
  { value: "1,200+", label: "Places mapped" },
  { value: "450+", label: "Events" },
  { value: "9,900+", label: "Hebrew & Greek entries" },
];

const FEATURES: {
  href: string;
  icon: IconType;
  title: string;
  description: string;
}[] = [
  {
    href: "/search",
    icon: LuSearch,
    title: "Search",
    description:
      "Find verses by meaning, not just matching words, with semantic, hybrid, or BM25 keyword search.",
  },
  {
    href: "/verses",
    icon: LuBookOpen,
    title: "Read",
    description:
      "Read full chapters in a clean, paragraph-style view with cross-references right where you need them.",
  },
  {
    href: "/notes",
    icon: LuNotebookPen,
    title: "Notes",
    description:
      "Personal commentary and research, anchored to a passage or a whole group of books.",
  },
  {
    href: "/lexicon",
    icon: LuLanguages,
    title: "Lexicon",
    description:
      "Dig into the original Hebrew and Greek behind any English word or Strong's number.",
  },
];

const STEPS: { icon: IconType; title: string; description: string }[] = [
  {
    icon: LuMessageCircleQuestion,
    title: "Ask naturally",
    description:
      'Type a phrase, theme, or question — like "a shepherd caring for lost sheep" — no exact wording required.',
  },
  {
    icon: LuBookOpen,
    title: "Read in context",
    description:
      "Jump straight into the full chapter with a clean reading view instead of an isolated, out-of-context verse.",
  },
  {
    icon: LuNetwork,
    title: "Go deeper",
    description:
      "Follow links to the people, places, and events involved, or trace a word back to its original Hebrew or Greek.",
  },
];

function FeatureCard({
  href,
  icon,
  title,
  description,
}: (typeof FEATURES)[number]) {
  return (
    <Link href={href}>
      <VStack
        align="start"
        gap="3"
        height="100%"
        rounded="xl"
        border="1px solid"
        borderColor="border"
        padding="5"
        transition="box-shadow 0.15s ease, border-color 0.15s ease"
        _hover={{ shadow: "md", borderColor: "orange.300" }}
      >
        <Box
          rounded="lg"
          bg="orange.subtle"
          color="orange.fg"
          padding="2.5"
          display="inline-flex"
        >
          <Icon as={icon} boxSize="5" />
        </Box>
        <Heading as="h3" size="md">
          {title}
        </Heading>
        <Text color="fg.muted" fontSize="sm">
          {description}
        </Text>
      </VStack>
    </Link>
  );
}

function HomePage() {
  return (
    <VStack align="stretch" gap={{ base: 12, md: 20 }} paddingBottom="8">
      <Box
        rounded="2xl"
        border="1px solid"
        borderColor="border"
        bg="orange.subtle"
        paddingX={{ base: 6, md: 12 }}
        paddingY={{ base: 10, md: 16 }}
        display="flex"
        flexDirection="column"
        alignItems="center"
        gap="5"
        textAlign="center"
      >
        <Badge
          colorPalette="orange"
          variant="solid"
          rounded="full"
          paddingX="3"
          paddingY="1"
          display="inline-flex"
          alignItems="center"
          gap="1.5"
        >
          <Icon as={LuSparkles} boxSize="3.5" />
          Semantic search meets biblical scholarship
        </Badge>

        <Heading
          as="h1"
          color="fg"
          fontWeight="semibold"
          fontSize={{ base: "3xl", md: "5xl" }}
          lineHeight="1.15"
          maxW="2xl"
        >
          Explore Scripture the way you actually think about it
        </Heading>

        <Text fontSize={{ base: "md", md: "lg" }} color="fg.muted" maxW="xl">
          SproutFaith is a Bible study tool that searches by meaning, not just
          keywords, and connects every verse to the people, places, events,
          and original Hebrew or Greek words behind it.
        </Text>

        <HStack gap="3" flexWrap="wrap" justify="center" paddingTop="2">
          <Button asChild size="lg" colorPalette="orange">
            <Link href="/search">
              Try a search
              <Icon as={LuArrowRight} />
            </Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/verses">Start reading</Link>
          </Button>
        </HStack>
      </Box>

      <SimpleGrid columns={{ base: 2, md: 4 }} gap="4">
        {STATS.map((stat) => (
          <VStack
            key={stat.label}
            gap="1"
            padding="4"
            rounded="lg"
            border="1px solid"
            borderColor="border"
            bg="bg.muted"
          >
            <Heading as="h3" size="2xl" color="orange.fg">
              {stat.value}
            </Heading>
            <Text fontSize="sm" color="fg.muted" textAlign="center">
              {stat.label}
            </Text>
          </VStack>
        ))}
      </SimpleGrid>

      <VStack align="stretch" gap="6">
        <VStack align="start" gap="1">
          <Heading as="h2" size="xl">
            Everything you need to study a passage
          </Heading>
          <Text color="fg.muted">
            Four ways into the text, all pointing back at each other.
          </Text>
        </VStack>
        <SimpleGrid columns={{ base: 1, sm: 2, lg: 3 }} gap="4">
          {FEATURES.map((feature) => (
            <FeatureCard key={feature.href} {...feature} />
          ))}
        </SimpleGrid>
      </VStack>

      <VStack align="stretch" gap="6">
        <Heading as="h2" size="xl">
          How it works
        </Heading>
        <SimpleGrid columns={{ base: 1, md: 3 }} gap="6">
          {STEPS.map((step, i) => (
            <VStack key={step.title} align="start" gap="2">
              <HStack gap="2" color="orange.fg">
                <Icon as={step.icon} boxSize="5" />
                <Text fontSize="sm" fontWeight="semibold">
                  Step {i + 1}
                </Text>
              </HStack>
              <Heading as="h3" size="md">
                {step.title}
              </Heading>
              <Text color="fg.muted" fontSize="sm">
                {step.description}
              </Text>
            </VStack>
          ))}
        </SimpleGrid>
      </VStack>

      <Box
        rounded="2xl"
        border="1px solid"
        borderColor="border"
        bg="bg.muted"
        padding={{ base: 6, md: 10 }}
        display="flex"
        flexDirection="column"
        alignItems="center"
        gap="4"
        textAlign="center"
      >
        <Heading as="h2" size="xl">
          Ready to dig in?
        </Heading>
        <Text color="fg.muted" maxW="md">
          Search for a theme, or start reading from wherever you like.
        </Text>
        <HStack gap="3" flexWrap="wrap" justify="center">
          <Button asChild colorPalette="orange">
            <Link href="/search">Search Scripture</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/verses">Browse verses</Link>
          </Button>
        </HStack>
      </Box>
    </VStack>
  );
}

export default HomePage;
