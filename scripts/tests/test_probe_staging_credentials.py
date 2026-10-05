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
                "projectToken": {
                    "environmentId": probe.ENVIRONMENT,
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
                "secret",
                self.opener({"data": {"projectToken": {"name": "production"}}}),
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
            "id": probe.PROJECT,
            "environments": {
                "edges": [{"node": {"id": probe.ENVIRONMENT, "name": "staging"}}]
            },
        }
        with patch.object(
            probe.subprocess,
            "run",
            return_value=Mock(returncode=0, stdout=json.dumps(payload)),
        ) as run:
            self.assertEqual(probe.cli_probe()["result"], "VERIFIED")
            args = run.call_args.args[0]
            self.assertEqual(
                args,
                [
                    "railway",
                    "status",
                    "--project",
                    probe.PROJECT,
                    "--environment",
                    probe.ENVIRONMENT,
                    "--json",
                ],
            )
            self.assertNotIn("api", args)

    def test_wrong_project_and_environment_block(self):
        for project, environment in [
            ("wrong", probe.ENVIRONMENT),
            (probe.PROJECT, "wrong"),
        ]:
            payload = {
                "data": {
                    "projectToken": {"projectId": project, "environmentId": environment}
                }
            }
            self.assertEqual(
                probe.probe("secret", self.opener(payload))["status"], "BLOCKED"
            )

    def test_scope_unrelated_queries_are_not_required(self):
        self.assertEqual(list(probe.PROBES), ["project_token_identity"])
        self.assertEqual(
            probe.PROBES["project_token_identity"],
            "query { projectToken { projectId environmentId } }",
        )

    def test_documented_http_transport_keeps_token_off_argv(self):
        payload = {
            "data": {
                "projectToken": {
                    "projectId": probe.PROJECT,
                    "environmentId": probe.ENVIRONMENT,
                }
            }
        }
        with patch.object(
            probe.subprocess,
            "run",
            return_value=Mock(returncode=0, stdout=json.dumps(payload) + "\n200"),
        ) as command:
            result = probe.probe("SECRET-SENTINEL")
        self.assertEqual(result["status"], "VERIFIED")
        self.assertNotIn("SECRET-SENTINEL", json.dumps(command.call_args.args))
        self.assertNotIn("SECRET-SENTINEL", json.dumps(result))
        self.assertIn("Project-Access-Token", command.call_args.kwargs["input"])
        self.assertNotIn("--location", command.call_args.args[0])
