import json, os, sys
os.environ.update({"APP_ENV": "development", "ADMIN_TOKEN": "test-admin-token-s2-e2e-0123456789abcdef", "SENTRY_DSN": "https://publickey@o1.ingest.us.sentry.io/2", "RAILWAY_GIT_COMMIT_SHA": "b"*40})
import sentry_sdk
from sentry_sdk.transport import Transport
sent = []
class Capture(Transport):
    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.headers.get("type") == "event": sent.append(item.payload.json)
import app.error_tracking as et
orig = et.init_options
et.init_options = lambda dsn, env: {**orig(dsn, env), "transport": Capture}
from fastapi.testclient import TestClient
from app.main import app
TEST_ADMIN_TOKEN = os.environ["ADMIN_TOKEN"]
c = TestClient(app, raise_server_exceptions=False)
r = c.get("/admin/observability/sentry-test?token=abc", headers={"X-Admin-Token": TEST_ADMIN_TOKEN, "Authorization": "Bearer eyJsecret", "Cookie": "s=secret"})
sentry_sdk.flush()
ev = sent[0]
print(r.status_code, len(sent), ev["environment"], ev["release"][:8], ev["exception"]["values"][-1]["type"])
print(json.dumps(ev.get("request"), indent=0))
blob = json.dumps(ev)
print([[(v["type"], v.get("value","")[:80]) for v in e["exception"]["values"]] for e in sent]); print("leaks:", [s for s in ("eyJsecret", "s=secret", TEST_ADMIN_TOKEN, "token=abc") if s in blob], "user" in ev, "vars" in blob)
