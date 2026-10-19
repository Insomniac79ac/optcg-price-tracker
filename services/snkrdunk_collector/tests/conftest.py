import os

# Scheduled-turn tests must not plan published discovery unless they opt in.
os.environ.setdefault("SNKRDUNK_AUTO_DISCOVERY", "false")
