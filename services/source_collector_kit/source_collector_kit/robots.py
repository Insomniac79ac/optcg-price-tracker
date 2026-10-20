"""robots.txt, fetched at the start of every run. Fails closed (plan §2.4)."""

from __future__ import annotations

from urllib.robotparser import RobotFileParser

from source_collector_kit.etiquette import USER_AGENT_TOKEN


class RobotsRefused(RuntimeError):
    """robots.txt could not be read, or it disallows a page the run needs. No run."""


class RobotsGate:
    def __init__(self, parser: RobotFileParser, body: str):
        self._parser = parser
        self.body = body

    @classmethod
    def from_response(cls, status: int, body: bytes) -> "RobotsGate":
        # Any answer but 200 is a fetch failure here, 404 included: the plan runs only on a
        # robots.txt we have actually read.
        if status != 200:
            raise RobotsRefused(f"robots.txt answered {status}")
        text = body.decode("utf-8", errors="replace")
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        return cls(parser, text)

    def allows(self, url: str) -> bool:
        return self._parser.can_fetch(USER_AGENT_TOKEN, url)

    def require(self, urls: list[str]) -> None:
        blocked = [u for u in urls if not self.allows(u)]
        if blocked:
            raise RobotsRefused(f"robots.txt disallows {len(blocked)} planned page(s), first {blocked[0]}")
