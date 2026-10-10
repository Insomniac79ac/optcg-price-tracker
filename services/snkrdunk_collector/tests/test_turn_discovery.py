"""Discovery never runs beside a live turn browser."""

from snkrdunk_collector import due


class FakeTurn:
    def __init__(self, order):
        self.order = order

    def discard(self, reason=None):
        self.order.append(("discard", reason))


def test_discovery_discards_the_turn_browser_first():
    # A second sync Playwright cannot start while the turn's runs in the same
    # thread ("Sync API inside the asyncio loop"); the next capture rewarms.
    order = []

    def discovery(*args, **kwargs):
        order.append(("discovery", args, kwargs))
        return "outcome"

    result = due._discovery_outside_turn(
        FakeTurn(order), discovery, "session", "claim", freshness="attempt"
    )
    assert result == "outcome"
    assert order == [
        ("discard", "discovery"),
        ("discovery", ("session", "claim"), {"freshness": "attempt"}),
    ]
