"""Standalone Railway deploy-log observability diagnostic.

Not part of the collector - imports nothing from browser/collect/db/writer.
Proves whether stdout/stderr from an exact deployment are captured across a
sleep boundary, with no network, DB, or credential access of any kind.

Invoke as: python -m snkrdunk_collector.runtime_probe
"""

import os
import sys
import time


def main() -> int:
    print("RUNTIME_PROBE_START")
    print(f"pid={os.getpid()}")
    sys.stdout.flush()

    time.sleep(15)

    print("RUNTIME_PROBE_STDERR", file=sys.stderr)
    sys.stderr.flush()

    print("RUNTIME_PROBE_END")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
