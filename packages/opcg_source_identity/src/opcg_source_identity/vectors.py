"""Small public conformance fixture, shared by service and image smoke tests."""

VECTORS = (
    ("snkrdunk", "https://snkrdunk.com/apparels/104428", "104428"),
    ("snkrdunk", "https://snkrdunk.com/en/trading-cards/104428", "104428"),
    ("snkrdunk", "https://snkrdunk.com/apparels/93522?q=1", "93522"),
    ("snkrdunk", "https://snkrdunk.com/en/trading-cards/142632#detail", "142632"),
    ("snkrdunk", "https://snkrdunk.com/apparels/no-id", None),
    ("snkrdunk", "https://example.com/apparels/104428", None),
    ("snkrdunk", None, None),
    ("yuyutei", "https://yuyu-tei.jp/sell/opc/card/st11/10002", "st11:10002"),
    ("yuyutei", " https://yuyu-tei.jp/sell/opc/card/promo-op10/00123 ", "promo-op10:00123"),
    ("yuyutei", "https://yuyu-tei.jp/sell/opc/card/st11/10004?x=1#p", "st11:10004"),
    ("yuyutei", "https://yuyu-tei.jp/sell/opc/card/st11/OP01-001", None),
    ("yuyutei", "https://example.com/sell/opc/card/st11/10002", None),
    ("yuyutei", None, None),
    ("other", "https://snkrdunk.com/apparels/104428", None),
)


def verify_contract(derive):
    for source, url, expected in VECTORS:
        assert derive(source, url) == expected, (source, url)
