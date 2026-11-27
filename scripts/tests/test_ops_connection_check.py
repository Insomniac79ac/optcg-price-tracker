"""Offline tests for the read-only staging database connection check."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ops import common  # noqa: E402
from ops import connection_check  # noqa: E402
from ops import db as ops_db  # noqa: E402


def _connect_kwargs(proxy, variables, statement_timeout_ms=60000):
    return dict(host=proxy["domain"], port=proxy["proxyPort"], user=variables["PGUSER"],
                password=variables["PGPASSWORD"], dbname=variables["PGDATABASE"], connect_timeout=15,
                options=ops_db.options(statement_timeout_ms))


class ConnectionCheck(unittest.TestCase):
    def _run(self, connect, row=(True, "TLSv1.3", "TLS_AES_256_GCM_SHA384"), verify=None):
        variables = {"PGUSER": "u", "PGPASSWORD": "secret-password", "PGDATABASE": "d"}
        proxy = {"domain": "example.invalid", "proxyPort": 1}
        conn = mock.Mock()
        conn.execute.return_value.fetchone.return_value = row
        opened = {}
        def _open(kwargs):
            opened.update(kwargs)
            return conn
        connect.side_effect = _open
        resolve = mock.patch.object(ops_db, "resolve", return_value=(proxy, variables))
        kwargs = mock.patch.object(ops_db, "connect_kwargs", side_effect=_connect_kwargs)
        fingerprint = mock.patch.object(ops_db, "verify", side_effect=verify)
        with tempfile.TemporaryDirectory() as tmp, resolve, kwargs, fingerprint, \
                mock.patch.object(connection_check, "_open", connect):
            result = connection_check.run(Path(tmp))
            written = json.loads((Path(tmp) / "connection-check.json").read_text())
        return result, written, opened, conn, variables

    def test_reports_encryption_separately_from_a_passing_fingerprint(self):
        connect = mock.Mock()
        result, written, opened, conn, variables = self._run(connect)
        self.assertEqual(result["tls"], {
            "negotiated": True, "protocol": "TLSv1.3", "cipher": "TLS_AES_256_GCM_SHA384",
        })
        self.assertEqual(result["fingerprint"], {"ok": True})
        self.assertEqual(written, result)
        self.assertEqual(opened["sslmode"], "require")
        self.assertNotIn("example.invalid", json.dumps({"tls": result["tls"], "fingerprint": result["fingerprint"]}))
        conn.close.assert_called()
        self.assertEqual(variables, {})  # cleared

    def test_fingerprint_failure_does_not_hide_encryption(self):
        connect = mock.Mock()
        result, written, opened, conn, _ = self._run(
            connect, verify=common.Refused("staging database fingerprint failed: tables"))
        self.assertEqual(result["tls"]["negotiated"], True)
        self.assertEqual(result["fingerprint"], {
            "ok": False, "reason": "staging database fingerprint failed: tables",
        })
        self.assertEqual(written, result)
        conn.close.assert_called()

    def test_output_has_no_host_port_user_password_or_connection_string(self):
        connect = mock.Mock()
        result, written, opened, conn, _ = self._run(connect)
        blob = json.dumps(result) + json.dumps(written)
        for forbidden in ("example.invalid", "secret-password", "PGPASSWORD", "://", ":1", "user=u"):
            self.assertNotIn(forbidden, blob)
        self.assertNotIn("host", result)
        self.assertNotIn("port", result)
        self.assertNotIn("user", result)
        self.assertNotIn("password", result)
        self.assertNotIn("dsn", result)
        self.assertNotIn("connection_string", result)

    def test_connection_errors_are_class_only(self):
        class FakeError(Exception):
            sqlstate = "08001"

        connect = mock.Mock(side_effect=FakeError("could not connect to server at example.invalid port 1"))
        variables = {"PGUSER": "u", "PGPASSWORD": "secret-password", "PGDATABASE": "d"}
        proxy = {"domain": "example.invalid", "proxyPort": 1}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(ops_db, "resolve", return_value=(proxy, variables)), \
                mock.patch.object(ops_db, "connect_kwargs", side_effect=_connect_kwargs), \
                mock.patch.object(connection_check, "_open", connect):
            with self.assertRaises(common.Refused) as raised:
                connection_check.run(Path(tmp))
        text = str(raised.exception)
        self.assertIn("staging database connection failed", text)
        self.assertNotIn("example.invalid", text)
        self.assertNotIn("secret-password", text)
        self.assertNotIn("port 1", text)
        # class-only: type and bucket, not the driver message
        self.assertIn("FakeError", text)
        self.assertNotIn("could not connect", text)
        self.assertEqual(variables, {})

    def test_unencrypted_session_is_reported_without_failing_the_check_itself(self):
        connect = mock.Mock()
        result, written, opened, conn, _ = self._run(connect, row=(False, None, None))
        self.assertEqual(result["tls"], {"negotiated": False})
        self.assertEqual(result["fingerprint"], {"ok": True})
        self.assertEqual(written, result)
        self.assertEqual(opened["sslmode"], "require")
