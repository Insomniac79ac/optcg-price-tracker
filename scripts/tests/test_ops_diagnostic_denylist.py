"""SEC-001 R13: the diagnostic SQL lint and the bounded print_ids input (offline).

Diagnostic results land in public Actions logs and artifacts, so scripts/ops/diagnostic.py refuses
SQL that runs a query given as text, hides code from the literal stripper, or names a user-data
table or credential column. This is a lint, not a control: the read-only session and the planned
SELECT-only database role are the controls.
"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ops import common, diagnostic, run  # noqa: E402


def refused(sql):
    try:
        diagnostic.parse(f"-- q\n{sql};\n")
    except common.Refused as error:
        return str(error)
    return None


class QueryFromText(unittest.TestCase):
    CASES = [
        "select query_to_xml('select 1', true, false, '')",
        "select query_to_xml_and_xmlschema('select 1', true, false, '')",
        "select query_to_xmlschema('select 1', true, false, '')",
        "select cursor_to_xml('c', 1, true, false, '')",
        "select cursor_to_xmlschema('c', true, false, '')",
        "select table_to_xml('prints', true, false, '')",
        "select table_to_xmlschema('prints', true, false, '')",
        "select schema_to_xml('public', true, false, '')",
        "select database_to_xml(true, false, '')",
        "select * from ts_stat('select v from t')",
        "select ts_rewrite('a'::tsquery, 'select t, s from aliases')",
        "select current_setting('server_version')",
        "select pg_stat_file('postgresql.conf')",
        "select lo_get(1)",
        "select pg_ls_waldir()",
        "select pg_read_file('x')",
        "select dblink('c', 'select 1')",
        "select dblink_exec('c', 'select 1')",
        "select * from crosstab('select 1')",
        "select * from crosstab3('select 1')",
        "select * from connectby('t', 'a', 'b', '1', 0)",
        "select to_regclass('prints')",
        "select to_regproc('now')",
        "select 'prints'::regclass",
        "select 'now'::regproc",
        "select regclass('prints')",
        "select cast('prints' as regclass)",
    ]

    def test_each_is_refused(self):
        for sql in self.CASES:
            with self.subTest(sql=sql):
                self.assertIsNotNone(refused(sql))

    def test_schema_qualified_quoted_and_mixed_case(self):
        for sql in ["select pg_catalog.query_to_xml('select 1', true, false, '')",
                    "select \"query_to_xml\"('select 1', true, false, '')",
                    "select Query_To_XML('select 1', true, false, '')",
                    "select pg_catalog.\"ts_rewrite\"('a'::tsquery, 'select 1')",
                    "select DBLINK_EXEC('c', 'select 1')"]:
            with self.subTest(sql=sql):
                self.assertIsNotNone(refused(sql))


class LiteralForms(unittest.TestCase):
    def test_hidden_after_escape_literal(self):
        # E'\'' ends where the '...' stripper does not, so the call would hide inside a "literal".
        self.assertIsNotNone(refused("select E'\\'', query_to_xml('select 1', true, false, '') , ''"))

    def test_escape_unicode_dollar_and_block_comment(self):
        for sql in ["select E'a'", "select e'a'", "select U&'d\\0061t'", "select U&\"d\\0061t\"",
                    "select $$a$$", "select $q$a$q$", "select /* ' */ 1 /* ' */"]:
            with self.subTest(sql=sql):
                self.assertIsNotNone(refused(sql))

    def test_plain_literal_e_is_not_refused(self):
        # snkrdunk-coverage-gap-*.sql uses the literal 'e'; the E'' check matches only at a token start.
        self.assertIsNone(refused("select 1 where 'x' <> 'e'"))
        self.assertIsNone(refused("select 1 where kind = 'e'"))


class SensitiveNames(unittest.TestCase):
    def test_user_tables_and_credential_columns_refused(self):
        for sql in ["select count(*) from users", "select email from prints", "select 1 from public.saved_views",
                    "select token from x", "select password_hash from x", "select google_sub from x",
                    "select traceback from app_log_events", "select context_json from app_log_events",
                    "select message from app_log_events"]:
            with self.subTest(sql=sql):
                self.assertIsNotNone(refused(sql))

    def test_counts_and_sizes_of_app_log_events_allowed(self):
        self.assertIsNone(refused("select count(*), sum(pg_column_size(e.*)) from app_log_events e"))

    def test_whole_identifier_only(self):
        self.assertIsNone(refused("select rarity_token from prints"))
        self.assertIsNone(refused("select 1 from prints where name = 'token email'"))


class ShippedDiagnostics(unittest.TestCase):
    def test_every_sql_file_present_parses(self):
        # Every .sql file present, not a fixed count (CP security b119fab).
        files = sorted(diagnostic.DIRECTORY.glob("*.sql"))
        self.assertTrue(files)
        self.assertEqual(sorted(p.stem for p in files), diagnostic.available())
        for path in files:
            with self.subTest(path=path.name):
                diagnostic.parse(path.read_text(), {"ELIGIBLE": "true"})


class PrintIds(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(diagnostic.parse_print_ids(""), [])
        self.assertEqual(diagnostic.parse_print_ids(" 3527, 12 "), [3527, 12])
        for raw in ["0", "-1", "1;drop", "1,,2", "a", "1.5", "1,1", ",".join(str(i) for i in range(1, 52))]:
            with self.subTest(raw=raw):
                with self.assertRaises(common.Refused):
                    diagnostic.parse_print_ids(raw)
        self.assertEqual(len(diagnostic.parse_print_ids(",".join(str(i) for i in range(1, 51)))), 50)

    def test_bound_as_parameter_never_formatted(self):
        statements = diagnostic.parse("-- q\nselect id from prints where id = any(%(print_ids)s::int[]);\n"
                                      "-- r\nselect 1;\n")
        calls = []

        class Conn:
            def execute(self, sql, params=None):
                calls.append((sql, params))
                return SimpleNamespace(fetchmany=lambda n: [])

            def rollback(self):
                pass

        diagnostic.execute(Conn(), statements, print_ids=[3527])
        self.assertEqual(calls[0][1], {"print_ids": [3527]})
        self.assertIn("%(print_ids)s", calls[0][0])
        self.assertNotIn("3527", calls[0][0])
        self.assertIsNone(calls[1][1])

    def test_declaring_statement_may_not_use_another_percent(self):
        self.assertIsNotNone(refused("select id from prints where id = any(%(print_ids)s::int[]) and name like '%a'"))

    def test_run_refuses_ids_for_a_diagnostic_without_the_input(self):
        with self.assertRaises(common.Refused):
            diagnostic.run("/tmp/unused", "work-by-state", "3527")

    def test_preflight_only_for_db_diagnostic(self):
        args = SimpleNamespace(runbook="staging-state", workflow="ops-readonly", apply=False,
                               print_ids="1", work_id=None, scope="", revision="", parent="")
        with self.assertRaises(common.Refused):
            run.preflight(args, read=None)
        args.runbook, args.print_ids = "db-diagnostic", "1,1"
        with self.assertRaises(common.Refused):
            run.preflight(args, read=None)


if __name__ == "__main__":
    unittest.main()
