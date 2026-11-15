"""Shared plumbing for the new shop collectors (new-sources plan §2.4).

Plain HTTP, one request at a time, an honest user agent, robots.txt checked at the start of every
run, the stop rule, the per-source dispatch budget, RAW written and committed before parsing, a
parser registry and a health report. Each collector (dorasuta_collector, later cardrush_collector)
is a thin package on this kit. Neither existing collector imports it, and it changes nothing they
import (scripts/collector_runtime_inputs.py).
"""
