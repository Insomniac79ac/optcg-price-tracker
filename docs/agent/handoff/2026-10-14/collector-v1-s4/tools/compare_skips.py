"""Compare skipped tests by id (JUnit XML) and by -rs reason between two runs."""
import json, re, sys, xml.etree.ElementTree as ET
def skips(path):
    out = {}
    for tc in ET.parse(path).iter("testcase"):
        s = tc.find("skipped")
        if s is not None:
            out[f'{tc.get("classname")}::{tc.get("name")}'] = (s.get("message") or "").strip()
    return out
def summary(path):
    return next(l.strip() for l in open(path) if re.search(r"\d+ passed", l))
base, head = skips(sys.argv[1] + ".xml"), skips(sys.argv[2] + ".xml")
only_base = sorted(set(base) - set(head)); only_head = sorted(set(head) - set(base))
reason_changed = sorted(k for k in set(base) & set(head) if base[k] != head[k])
print(json.dumps({
  "baseline": {"run": sys.argv[1].rsplit("/", 1)[-1], "summary": summary(sys.argv[1] + ".txt"), "skipped": len(base)},
  "s3": {"run": sys.argv[2].rsplit("/", 1)[-1], "summary": summary(sys.argv[2] + ".txt"), "skipped": len(head)},
  "identical_skip_set": not only_base and not only_head,
  "only_in_baseline": only_base, "only_in_s3": {k: head[k] for k in only_head},
  "same_id_reason_changed": {k: [base[k], head[k]] for k in reason_changed},
  "skipped_ids": {k: base[k] for k in sorted(base)},
}, indent=1))
