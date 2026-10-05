import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import probe_staging_credentials as probe


class Response(io.StringIO):
    status = 200


class ProbeTests(unittest.TestCase):
    def opener(self, payload):
        opener = Mock()
        opener.open.side_effect = lambda *a, **k: Response(json.dumps(payload))
        return opener

    def test_destination_and_no_values(self):
        payload = {
            "data": {
                "environment": {
                    "id": probe.ENVIRONMENT,
                    "name": "staging",
                    "projectId": probe.PROJECT,
                    "meta": "SECRET-SENTINEL",
                }
            }
        }
        result = probe.probe("SECRET-SENTINEL", self.opener(payload))
        self.assertEqual(result["status"], "VERIFIED")
        self.assertNotIn("SECRET-SENTINEL", json.dumps(result))

    def test_wrong_destination(self):
        self.assertEqual(
            probe.probe(
                "secret", self.opener({"data": {"environment": {"name": "production"}}})
            )["status"],
            "BLOCKED",
        )

    def test_null_data_preserves_safe_error_code(self):
        payload = {
            "data": None,
            "errors": [
                {
                    "message": "SECRET-SENTINEL",
                    "path": ["environment", "SECRET-SENTINEL"],
                    "extensions": {"code": "FORBIDDEN"},
                }
            ],
        }
        result = probe.probe("secret", self.opener(payload))
        self.assertEqual(result["probes"][0]["error_codes"], ["FORBIDDEN"])
        self.assertNotIn("SECRET-SENTINEL", json.dumps(result))

    def test_http_denial_and_transport_are_sanitized(self):
        for error in [
            urllib.error.HTTPError(probe.ENDPOINT, 403, "SECRET-SENTINEL", {}, None),
            ValueError("SECRET-SENTINEL"),
        ]:
            opener = Mock()
            opener.open.side_effect = error
            result = probe.probe("secret", opener)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertNotIn("SECRET-SENTINEL", json.dumps(result))

    def test_redirect_refused(self):
        with self.assertRaises(ValueError):
            probe.NoRedirect().redirect_request(
                None, None, 302, None, None, "https://example.org"
            )

    def test_cli_usage_failure_is_not_credential_failure(self):
        with patch.object(
            probe.subprocess,
            "run",
            return_value=Mock(
                returncode=2, stderr="unexpected argument SECRET-SENTINEL", stdout=""
            ),
        ):
            result = probe.cli_probe()
        self.assertEqual(result["error_codes"], ["CLI_USAGE"])
        self.assertNotIn("SECRET-SENTINEL", json.dumps(result))

    def test_cli_success_requires_destination(self):
        payload = {
            "data": {
                "environment": {
                    "id": probe.ENVIRONMENT,
                    "name": "staging",
                    "projectId": probe.PROJECT,
                }
            }
        }
        with patch.object(
            probe.subprocess,
            "run",
            return_value=Mock(returncode=0, stdout=json.dumps(payload)),
        ):
            self.assertEqual(probe.cli_probe()["result"], "VERIFIED")
