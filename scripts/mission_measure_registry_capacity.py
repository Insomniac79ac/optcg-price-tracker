"""Local synthetic transport benchmark; no valid new identity or source IO."""

import copy, json, statistics, tempfile, time, tracemalloc
from pathlib import Path
from app.services import physical_artwork_proof as module

current = json.loads(module.REGISTRY.read_text())
proofs = []
for offset in range(1000):
    proof = copy.deepcopy(current["proofs"][offset % len(current["proofs"])])
    proof["source_candidate_id"] = offset + 1
    proofs.append(proof)
fixture = {"schema_version": 1, "target": "staging", "proofs": proofs}
with tempfile.TemporaryDirectory(prefix="physical-registry-capacity-") as directory:
    path = Path(directory) / "synthetic.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2))
    module.REGISTRY = path
    assert path.stat().st_size <= module.MAX_REGISTRY_BYTES
    timings = []
    for iteration in range(100):
        start = time.perf_counter()
        loaded = module.registry()
        assert len(loaded) == 1000
        timings.append((time.perf_counter() - start) * 1000)
    tracemalloc.start()
    module.registry()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result = {
        "target": "local_synthetic",
        "synthetic_proofs": 1000,
        "bytes": path.stat().st_size,
        "byte_bound": module.MAX_REGISTRY_BYTES,
        "iterations": len(timings),
        "load_mean_ms": statistics.mean(timings),
        "load_p95_ms": sorted(timings)[94],
        "load_max_ms": max(timings),
        "peak_traced_allocation_bytes": peak,
        "unbatched_5000_loads_estimated_seconds": statistics.mean(timings) * 5,
        "serial_16_work_loads_estimated_seconds": statistics.mean(timings) * 16 / 1000,
        "source_requests": 0,
        "database_writes": 0,
        "valid_new_identity_claims": 0,
        "synthetic_fixture_ephemeral": True,
    }
    print(json.dumps(result))
    Path(
        "docs/agent/evidence/physical-registry-capacity-local-2026-10-07.json"
    ).write_text(json.dumps(result, indent=2) + "\n")
