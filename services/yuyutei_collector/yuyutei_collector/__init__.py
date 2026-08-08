"""Permanent Yuyu-Tei collector service.

Runs a bounded, fail-closed collection for one approved
source_card_mapping at a time and exits - see collect.py. Extraction logic
originates from spikes/yuyutei-browser-feasibility/spike.py's
extract_with_agreement (selector_version v3), live-validated there before
being moved here; this package does not import from spikes/.
"""
