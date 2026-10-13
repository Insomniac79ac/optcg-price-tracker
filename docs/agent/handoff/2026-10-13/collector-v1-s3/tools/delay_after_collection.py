"""Sleep DELAY_AFTER_COLLECTION seconds between collection and the first test.
Proves tokens are not minted at collection time (their expiry is 60 s)."""
import os, time

def pytest_collection_finish(session):
    seconds = float(os.environ.get("DELAY_AFTER_COLLECTION", "0"))
    if seconds:
        print(f"\n[delay_after_collection] sleeping {seconds}s after collecting {len(session.items)} tests")
        time.sleep(seconds)
