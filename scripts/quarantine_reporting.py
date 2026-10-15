"""Report identity-quarantined (blocked) refresh work as its own category.

Owner decision 2026-10-14: quarantined/blocked items are reported separately, with
their count and oldest age always visible, and are excluded from overdue work and
freshness deadline compliance. No threshold, budget or target changes; real overdue
work still fails every check.

Tooling only. The shared aggregate (`app.services.operational_health`) and its SQL
are collector runtime inputs, so they are not changed; this module adjusts their
inputs and output inside the state tooling. It is not imported by any collector.

Fail closed: without the per-item quarantine list (older evidence), or when the list
disagrees with the authoritative per-shard `quarantined` count, nothing is excluded
and the previous, stricter reporting applies.
"""

from copy import deepcopy
from datetime import datetime, timedelta

from app.services.operational_health_sql import ELIGIBLE

# Same eligible population as DUE_SQL. `since` is the latest change to the blocked
# work row: the item has been blocked at least since then, so it is a safe lower
# bound for "quarantined throughout an execution".
QUARANTINE_SQL = (
    "with e as ("
    + ELIGIBLE
    + """) select e.source, case when e.source='yuyutei' then e.shard else null end shard,
 e.checked_at, w.updated_at since
 from e join freshness_work w on w.id=e.work_id where e.state='blocked'
 order by e.source, e.mapping_id"""
)
ITEM_FIELDS = ("source", "shard", "checked_at", "since")
QUARANTINE_COLUMNS = ("quarantined", "quarantined_never_successfully_checked",
                      "quarantined_check_older_than_24h", "quarantined_oldest_since")
ALIASES = (("yuyutei", "yuyu"), ("snkrdunk", "snkrdunk"))
EXCLUDED_FROM = ["overdue", "never_checked", "deadline_misses", "due_work_deficit", "deadline_compliance"]


def _at(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _hours(now, then):
    return None if then is None else round((now - then).total_seconds() / 3600, 1)


def _overdue(item, at):
    return item["checked_at"] is None or item["checked_at"] < at - timedelta(hours=24)


def _items(raw):
    return [
        {"source": i["source"], "shard": i["shard"], "checked_at": _at(i["checked_at"]), "since": _at(i["since"])}
        for i in raw
    ]


def consistent(due_rows, items):
    """Each source/shard's listed items must equal its authoritative quarantined count."""
    listed = {}
    for item in items:
        key = (item["source"], item["shard"])
        listed[key] = listed.get(key, 0) + 1
    for row in due_rows:
        if (row.get("quarantined") or 0) != listed.pop((row["source"], row["shard"]), 0):
            return False
    return not listed


def summary(items, now):
    """Count and oldest age; present (zero, None) when nothing is quarantined."""
    oldest_since = min((i["since"] for i in items if i["since"]), default=None)
    checked = [i["checked_at"] for i in items if i["checked_at"]]
    return {
        "count": len(items),
        "overdue": sum(_overdue(i, now) for i in items),
        "never_checked": sum(i["checked_at"] is None for i in items),
        "oldest_blocked_since": oldest_since.isoformat() if oldest_since else None,
        "oldest_blocked_age_hours": _hours(now, oldest_since),
        "oldest_successful_check_age_hours": _hours(now, min(checked)) if checked else None,
        "excluded_from": EXCLUDED_FROM,
    }


def actionable_due_rows(due_rows, items, now):
    """DUE rows with quarantined items removed from every deadline counter."""
    rows = deepcopy(due_rows)
    for row in rows:
        mine = [i for i in items if i["source"] == row["source"] and i["shard"] == row["shard"]]
        overdue = [i for i in mine if _overdue(i, now)]
        older = [i for i in overdue if i["checked_at"] is not None]
        due = [i for i in mine if i["checked_at"] is None or i["checked_at"] <= now - timedelta(hours=23)]
        between = [i for i in due if i not in overdue]
        for key, n in (("due", len(due)), ("overdue", len(overdue)), ("over_24h", len(older)),
                       ("between_23_24h", len(between)),
                       ("never_checked", sum(i["checked_at"] is None for i in mine))):
            if row.get(key) is not None:
                row[key] = max(0, row[key] - n)
        row["quarantined_excluded"] = row.get("quarantined") or 0
        row["quarantined"] = 0
    return rows


def actionable_run(run, items):
    """A run summary without items provably quarantined and overdue for the whole run.

    The collector counted deadline misses from DUE_SQL at the end of its run. Only items
    blocked since before the run started (and still blocked) and already overdue at its
    start are removed; anything else stays counted, so a real miss is never hidden.
    """
    run = deepcopy(run)
    identity, freshness = run.get("identity") or {}, run.get("freshness") or {}
    started = _at(identity.get("started_at"))
    if started is None:
        return run
    mine = [
        i for i in items
        if i["source"] == identity.get("source")
        and (identity.get("shard") is None or i["shard"] == identity.get("shard"))
        and i["since"] is not None and i["since"] <= started
    ]
    for key, n in (("deadline_misses", sum(_overdue(i, started) for i in mine)),
                   ("never_checked", sum(i["checked_at"] is None for i in mine))):
        if freshness.get(key) is not None:
            freshness[key] = max(0, freshness[key] - n)
    return run


def aggregate(health, due_rows, runs, budgets, now, raw_items):
    """`health.aggregate` over actionable work, with the quarantine reported separately."""
    at = _at(now)
    items = None if raw_items is None else _items(raw_items)
    if items is None or not consistent(due_rows, items):
        result = health.aggregate(due_rows, runs, budgets, now)
        state = "not_reported" if items is None else "inconsistent; not excluded"
        for _, alias in ALIASES:
            result[alias]["quarantine"] = {"count": result[alias]["identity_quarantine"], "reporting": state}
        result["raw_due_work"]["quarantine"] = {"count": result["raw_due_work"]["quarantined"], "reporting": state}
        return result
    result = health.aggregate(
        actionable_due_rows(due_rows, items, at), [actionable_run(r, items) for r in runs], budgets, now
    )
    for source, alias in ALIASES:
        mine = [i for i in items if i["source"] == source]
        result[alias]["identity_quarantine"] = len(mine)
        result[alias]["due_work"]["quarantined"] = len(mine)
        result[alias]["quarantine"] = summary(mine, at) | {"reporting": "separate"}
    result["raw_due_work"]["quarantined"] = len(items)
    result["raw_due_work"]["quarantine"] = summary(items, at) | {"reporting": "separate"}
    return result


def freshness(rows, now):
    """Per-source freshness with quarantined work reported beside, not inside, the deficit.

    Rows without the quarantine columns (older evidence) keep the stricter old meaning.
    """
    at = _at(now)
    out = {}
    for row in rows:
        r = {k: v for k, v in row.items() if k != "name"}
        q = r.get("quarantined")
        if q is None:
            for key in QUARANTINE_COLUMNS:
                r.pop(key, None)
        else:
            since = _at(r.get("quarantined_oldest_since"))
            r["actionable_never_successfully_checked"] = r["never_successfully_checked"] - r["quarantined_never_successfully_checked"]
            r["actionable_check_older_than_24h"] = r["check_older_than_24h"] - r["quarantined_check_older_than_24h"]
            r["quarantine"] = {
                "count": q,
                "never_successfully_checked": r.pop("quarantined_never_successfully_checked"),
                "check_older_than_24h": r.pop("quarantined_check_older_than_24h"),
                "oldest_blocked_since": since.isoformat() if since else None,
                "oldest_blocked_age_hours": _hours(at, since),
                "excluded_from": ["deadline_compliance"],
            }
            r.pop("quarantined"), r.pop("quarantined_oldest_since", None)
        out[row["name"]] = r
    return out


def deficit(by_source):
    """True when actionable (non-quarantined) work misses the 24 h target."""
    return any(
        r.get("actionable_never_successfully_checked", r["never_successfully_checked"])
        or r.get("actionable_check_older_than_24h", r["check_older_than_24h"])
        for r in by_source.values()
    )
