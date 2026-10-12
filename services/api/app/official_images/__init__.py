"""Self-hosted copies of the official Bandai card list images.

Deliberately a separate package that no collector imports (see
scripts/collector_runtime_inputs.py): adding or changing it must never make an
API change a collector release. Nothing here touches identity, prices, the
Market Index or Market Value. Yuyu-Tei and SNKRDUNK images are out of scope.
"""
