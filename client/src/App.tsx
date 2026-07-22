import { Box, Container, Flex, HStack, Heading, Text } from "@chakra-ui/react";
import { Link, Route, Switch, useLocation } from "wouter";
import SearchPage from "@/pages/SearchPage";
import VersesPage from "@/pages/VersesPage";
import EventsPage from "@/pages/EventsPage";
import GroupsPage from "@/pages/GroupsPage";
import LexiconPage from "@/pages/LexiconPage";
import HomePage from "@/pages/HomePage";

const NAV_LINKS = [
  { href: "/search", label: "Search" },
  { href: "/verses", label: "Verses" },
  { href: "/events", label: "Events" },
  { href: "/groups", label: "People Groups" },
  { href: "/lexicon", label: "Lexicon" },
];

function NavLink({ href, label }: { href: string; label: string }) {
  const [location] = useLocation();
  const active = location === href;

  return (
    <Link href={href}>
      <Text
        as="span"
        px="3"
        py="1.5"
        borderRadius="md"
        fontWeight={active ? "semibold" : "normal"}
        color={active ? "orange.fg" : "fg.muted"}
        bg={active ? "orange.subtle" : "transparent"}
        _hover={{ bg: active ? "orange.subtle" : "bg.muted" }}
        cursor="pointer"
      >
        {label}
      </Text>
    </Link>
  );
}

function App() {
  return (
    <Box minH="100svh">
      <Box borderBottomWidth="1px" borderColor="border">
        <Container maxW="4xl" py="4">
          <Flex align="center" justify="space-between" gap={2} flexFlow="wrap">
            <Link href="/">
              <Heading size="md">SproutFaith</Heading>
            </Link>
            <HStack gap="1">
              {NAV_LINKS.map((link) => (
                <NavLink key={link.href} {...link} />
              ))}
            </HStack>
          </Flex>
        </Container>
      </Box>

      <Container maxW="4xl" py="8">
        <Switch>
          <Route path="/search" component={SearchPage} />
          <Route path="/verses" component={VersesPage} />
          <Route path="/events" component={EventsPage} />
          <Route path="/groups" component={GroupsPage} />
          <Route path="/lexicon" component={LexiconPage} />
          <Route path="/" component={HomePage} />
        </Switch>
      </Container>
    </Box>
  );
}

export default App;
