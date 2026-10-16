"""Staging Postgres volume growth: planning and stress rates, with and without named events.

Merges the session 13 handoff tools volume_series.py, storage_rates_current.py and
storage_rates_ex_batch.py. Definitions are unchanged:
- samples strictly after ``window_start`` (current collector code), Railway DISK_USAGE_GB
  on the s9 basis (GB x 1024);
- planning = average daily growth over the window; stress = worst rolling 24 h;
- a named step (one-off batch) is removed from every later sample;
- a named transient's samples (more than ``threshold_mb`` above the line between the
  samples at its ends) are left out of the stress rate.
Three variants are always reported: as observed, steps removed (stress A), steps removed
and the chosen transients excluded (stress B). Read-only: one Railway metrics query.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

from ops import common

EVENTS = Path(__file__).with_name("storage_events.json")
DAY = timedelta(hours=24)


def load_events(path=EVENTS):
    return json.loads(Path(path).read_text())


def parse_points(series):
    """[(datetime, MB s9)] from {'measurements': {'DISK_USAGE_GB': [{ts, value}]}}."""
    points = []
    for row in series["measurements"]["DISK_USAGE_GB"]:
        if row.get("value") is not None:
            points.append((datetime.fromisoformat(row["ts"]), row["value"] * 1024))
    return sorted(points)


def fetch_series(since, sample_seconds=300):
    """Railway metrics, staging Postgres service only (pinned identity)."""
    import generate_staging_state as state
    from datetime import timezone

    state.staging_environment()
    data = state.railway(
        f'query {{ metrics(projectId:"{state.PROJECT}", environmentId:"{state.ENVIRONMENT}", '
        f'serviceId:"{state.POSTGRES}", measurements:[DISK_USAGE_GB], startDate:"{since}", '
        f'sampleRateSeconds:{int(sample_seconds)}) {{ measurement values {{ ts value }} }} }}')
    out = {"environment": "staging", "observed_at": state.timestamp(), "measurements": {}}
    for m in data["metrics"]:
        out["measurements"][m["measurement"]] = [
            {"ts": datetime.fromtimestamp(v["ts"], timezone.utc).isoformat(), "value": v["value"]}
            for v in m["values"]]
    return out


def _at_or_before(by, t):
    keys = [k for k in by if k <= t]
    if not keys:
        raise common.Refused(f"no sample at or before {t.isoformat()}")
    return by[max(keys)]


def _at_or_after(by, t):
    keys = [k for k in by if k >= t]
    if not keys:
        raise common.Refused(f"no sample at or after {t.isoformat()}")
    return by[min(keys)]


def remove_steps(points, steps):
    """Subtract each step's rise from the samples after its start (as storage_rates_ex_batch)."""
    out = list(points)
    report = {}
    for name, step in steps.items():
        start, end = datetime.fromisoformat(step["from"]), datetime.fromisoformat(step["to"])
        by = dict(out)
        if not out or out[-1][0] <= start:
            report[name] = {"applied": False, "reason": "outside the window"}
            continue
        before, after = _at_or_before(by, start), _at_or_after(by, end)
        out = [(t, v - (min(v, after) - before) if t > start else v) for t, v in out]
        report[name] = {"applied": True, "from": step["from"], "to": step["to"], "mb_s9": round(after - before, 1)}
    return out, report


def transient_samples(points, transient):
    start, end = datetime.fromisoformat(transient["from"]), datetime.fromisoformat(transient["to"])
    by = dict(points)
    if start not in by or end not in by:
        return [], None
    def settled(t):
        return by[start] + (by[end] - by[start]) * (t - start).total_seconds() / (end - start).total_seconds()
    hits = [(t, v - settled(t)) for t, v in points if start < t < end and v - settled(t) > transient["threshold_mb"]]
    peak = max(hits, key=lambda x: x[1]) if hits else None
    return [t for t, _ in hits], peak


def worst_rolling(points):
    by = dict(points)
    rolling = [(t, by[t + DAY] - v) for t, v in points if t + DAY in by]
    if not rolling:
        return None
    t, growth = max(rolling, key=lambda x: x[1])
    return {"start": t.isoformat(), "mb_day_s9": round(growth, 2), "windows_compared": len(rolling)}


def planning(points):
    (t0, v0), (t1, v1) = points[0], points[-1]
    hours = (t1 - t0).total_seconds() / 3600
    return round((v1 - v0) * 24 / hours, 2) if hours > 0 else None


def runway(room, rate):
    return round(room / rate, 1) if rate and rate > 0 else None


def compute(series, events=None, transients=None):
    """Rates for every variant. ``transients``: names to exclude (default: all named)."""
    events = events or load_events()
    start = datetime.fromisoformat(events["window_start"])
    raw = [(t, v) for t, v in parse_points(series) if t > start]
    if len(raw) < 2:
        raise common.Refused("not enough volume samples in the window")
    names = list(events.get("transients", {})) if transients is None else list(transients)
    unknown = [n for n in names if n not in events.get("transients", {})]
    if unknown:
        raise common.Refused("unknown transient: " + ", ".join(unknown))
    adj, steps = remove_steps(raw, events.get("steps", {}))
    excluded, transient_report = set(), {}
    for name in names:
        hits, peak = transient_samples(adj, events["transients"][name])
        excluded.update(hits)
        transient_report[name] = {"samples": len(hits), "peak_above_settled_mb": round(peak[1], 1) if peak else 0,
                                  "peak_at": peak[0].isoformat() if peak else None}
    room = round(events["reserve_ceiling_mb_s9"] - raw[-1][1], 1)
    hours = (raw[-1][0] - raw[0][0]).total_seconds() / 3600
    variants = {
        "as_observed": raw,
        "ex_steps": adj,
        "ex_steps_ex_transients": [(t, v) for t, v in adj if t not in excluded],
    }
    out = {"read_only": True, "database_writes": 0, "source_requests": 0,
           "window": {"start": events["window_start"], "first_sample": raw[0][0].isoformat(),
                      "last_sample": raw[-1][0].isoformat(), "hours": round(hours, 2), "samples": len(raw),
                      "meets_72h": hours >= 72},
           "volume_mb_s9": round(raw[-1][1], 1), "room_to_reserve_mb_s9": room,
           "steps": steps, "transients_excluded": transient_report, "variants": {}}
    for name, points in variants.items():
        plan = planning(points)
        stress = worst_rolling(points)
        out["variants"][name] = {
            "planning_mb_day_s9": plan, "stress_worst_rolling_24h": stress,
            "runway_days_planning": runway(room, plan),
            "runway_days_stress": runway(room, stress and stress["mb_day_s9"]),
        }
    by = dict(adj)
    last = raw[-1][0]
    out["last_24h_mb_s9"] = round(adj[-1][1] - by[last - DAY], 2) if last - DAY in by else None
    return out


def fit(rates, one_off_mb, room, horizon_days=90, recurring_mb_day=0.0):
    """Does a one-off of ``one_off_mb`` fit the horizon at each rate? (remaining50_fit.py)."""
    out = {}
    for name, rate in rates.items():
        need = rate * horizon_days + one_off_mb + recurring_mb_day * horizon_days
        out[name] = {"mb_day": rate, "need_mb": round(need, 1), "margin_mb": round(room - need, 1),
                     "fits": need <= room, "margin_no_batch_mb": round(room - rate * horizon_days, 1)}
    return out


def run(out_dir, transients=None):
    events = load_events()
    series = fetch_series(events["window_start"])
    common.write_json(Path(out_dir) / "volume-series.json", series)
    result = compute(series, events, transients)
    common.write_json(Path(out_dir) / "storage-rates.json", result)
    v = result["variants"]
    return {"volume_mb_s9": result["volume_mb_s9"], "room_to_reserve_mb_s9": result["room_to_reserve_mb_s9"],
            "planning_mb_day": v["ex_steps"]["planning_mb_day_s9"],
            "stress_as_observed_mb_day": (v["as_observed"]["stress_worst_rolling_24h"] or {}).get("mb_day_s9"),
            "stress_A_ex_steps_mb_day": (v["ex_steps"]["stress_worst_rolling_24h"] or {}).get("mb_day_s9"),
            "stress_B_ex_transients_mb_day": (v["ex_steps_ex_transients"]["stress_worst_rolling_24h"] or {}).get("mb_day_s9"),
            "transients_excluded": sorted(result["transients_excluded"]),
            "last_24h_mb_s9": result["last_24h_mb_s9"]}
