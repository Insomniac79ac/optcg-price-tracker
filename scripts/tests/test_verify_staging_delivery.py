import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError, URLError
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_staging_delivery import validate_state, get, state, wait_for_delivery, run_component_checks, decide_api, resolve_api_sha


class VerificationTests(unittest.TestCase):
    def test_natural_checks_keep_full_bounded_cycle_and_other_checks_keep_300s(self):
        checks = [
            "scripts/verify_yuyu_raw_reader_component.py",
            "scripts/verify_snkr_published_discovery_component.py",
            "scripts/verify_staging_delivery.py",
        ]
        with patch("verify_staging_delivery.subprocess.run") as run:
            run_component_checks(checks)
        bounds = {
            Path(call.args[0][1]).name: call.kwargs["timeout"]
            for call in run.call_args_list
        }
        self.assertEqual(bounds["verify_yuyu_raw_reader_component.py"], 1860)
        self.assertEqual(bounds["verify_snkr_published_discovery_component.py"], 1860)
        self.assertEqual(bounds["verify_staging_delivery.py"], 300)

    def test_component_checks_refuse_outside_repository_before_launch(self):
        with patch("verify_staging_delivery.subprocess.run") as run:
            with self.assertRaises(state.VerificationError):
                run_component_checks(["/tmp/unreviewed.py"])
        run.assert_not_called()

    def setUp(self):
        path = Path(__file__).resolve().parents[2] / 'docs/agent/evidence/staging-state-3391abad5c997c5a.json'
        self.evidence = json.loads(path.read_text())
        self.expected = self.evidence['repository']['sha']
        self.evidence['frontend']['sha'] = self.expected
        self.api_sha = next(s['git_sha'] for s in self.evidence['railway']['services'] if s['name'] == 'optcg-price-tracker')

    def validate(self, evidence=None):
        validate_state(evidence or self.evidence, self.expected, self.api_sha, 'c4e8a1d7b902')

    def test_good_live_identity_and_core_database_invariants(self):
        self.validate()

    def test_native_api_build_can_finish_after_frontend_without_false_failure(self):
        pending = copy.deepcopy(self.evidence)
        api = next(s for s in pending['railway']['services'] if s['name']=='optcg-price-tracker')
        api.update(git_sha='0'*40, status='BUILDING')
        collect = Mock(side_effect=[pending, self.evidence])
        sleep = Mock()
        result = wait_for_delivery(self.expected, self.api_sha, 100, collect=collect,
                                   clock=lambda: 0, sleep=sleep)
        self.assertEqual(result['repository']['sha'], self.expected)
        self.assertEqual(collect.call_count, 2)
        sleep.assert_called_once_with(15)

    def test_wait_remains_bounded_and_rejects_branch_change(self):
        pending = copy.deepcopy(self.evidence)
        next(s for s in pending['railway']['services'] if s['name']=='optcg-price-tracker')['status']='BUILDING'
        with self.assertRaises(state.VerificationError):
            wait_for_delivery(self.expected,self.api_sha,0,collect=lambda:pending,clock=lambda:0,sleep=Mock())
        moved = copy.deepcopy(pending)
        moved['repository']['sha']='0'*40
        with self.assertRaises(state.VerificationError):
            wait_for_delivery(self.expected,self.api_sha,100,collect=lambda:moved,clock=lambda:0,sleep=Mock())

    def test_fail_closed_on_identity_or_integrity_change(self):
        for mutate in (
            lambda e: e.update(mode='fixture'),
            lambda e: e['frontend'].update(sha='0' * 40),
            lambda e: e['repository'].update(sha='0' * 40),
            lambda e: e['database'].update(duplicate_active_exact_print_source_groups=1),
            lambda e: e['database']['market_value'][0].update(intentional_gap_rows=1),
            lambda e: e['database']['coverage'][0].update(canonical_variants=0),
            lambda e: e['database']['revision'][0].update(version_num='unexpected'),
        ):
            e = copy.deepcopy(self.evidence)
            mutate(e)
            with self.assertRaises(state.VerificationError):
                self.validate(e)

    def test_nonstaging_destinations_refused_before_network(self):
        for url in ('https://example.com/health', 'https://optcg-price-tracker-staging.vercel.app.evil.test/'):
            with self.assertRaises(state.VerificationError):
                get(url)

    def test_rate_limit_obeys_one_bounded_server_retry(self):
        body = StringIO('{}')
        body.headers = {}
        opener = Mock()
        opener.open.side_effect = [HTTPError('staging', 429, 'limited', {'Retry-After': '2'}, None), body]
        with patch('verify_staging_delivery.urllib.request.build_opener', return_value=opener), patch('verify_staging_delivery.time.sleep') as sleep:
            self.assertEqual(get('https://optcg-price-tracker-staging.vercel.app/api/version'), {})
            sleep.assert_called_once_with(2)
            self.assertEqual(opener.open.call_count, 2)

    def test_unbounded_or_repeated_rate_limit_fails(self):
        for retry in ('0', '301'):
            opener = Mock()
            opener.open.side_effect = HTTPError('staging', 429, 'limited', {'Retry-After': retry}, None)
            with patch('verify_staging_delivery.urllib.request.build_opener', return_value=opener):
                with self.assertRaises(state.VerificationError):
                    get('https://optcg-price-tracker-staging.vercel.app/api/version')
                self.assertEqual(opener.open.call_count, 1)


    def opener_with(self, *effects):
        opener = Mock()
        opener.open.side_effect = list(effects)
        return opener

    def body(self, text='{}'):
        response = StringIO(text)
        response.headers = {}
        return response

    def test_timeout_then_success_retries_and_records(self):
        import verify_staging_delivery as v
        v.timeout_retries.clear()
        opener = self.opener_with(TimeoutError('read timed out'), URLError(TimeoutError('connect')), self.body('{"ok": true}'))
        with patch('verify_staging_delivery.urllib.request.build_opener', return_value=opener), patch('verify_staging_delivery.time.sleep') as sleep:
            self.assertEqual(get('https://optcg-price-tracker-staging.vercel.app/api/version'), {'ok': True})
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 5])
        self.assertEqual([r['attempt'] for r in v.timeout_retries], [1, 2])

    def test_timeout_exhausted_fails_after_two_retries(self):
        import verify_staging_delivery as v
        v.timeout_retries.clear()
        opener = self.opener_with(*[TimeoutError('timed out')] * 4)
        with patch('verify_staging_delivery.urllib.request.build_opener', return_value=opener), patch('verify_staging_delivery.time.sleep'):
            with self.assertRaises(TimeoutError):
                get('https://optcg-price-tracker-staging.vercel.app/api/version')
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual(len(v.timeout_retries), 2)

    def test_non_timeout_failures_are_never_retried(self):
        for error in (HTTPError('staging', 500, 'error', {}, None), URLError('connection refused'),
                      state.VerificationError('Unexpected HTTP redirect; destination not verified')):
            opener = self.opener_with(error, self.body())
            with patch('verify_staging_delivery.urllib.request.build_opener', return_value=opener), patch('verify_staging_delivery.time.sleep') as sleep:
                with self.assertRaises(type(error)):
                    get('https://optcg-price-tracker-staging.vercel.app/api/version')
            self.assertEqual(opener.open.call_count, 1)
            sleep.assert_not_called()

    def test_assertion_failure_on_content_is_not_retried(self):
        # A sale price leak is a content assertion in the caller: get() returns
        # once, the caller fails, and nothing re-requests to look for a better answer.
        import verify_staging_delivery as v
        opener = self.opener_with(self.body('{"observations": [{"id": 7}]}'), self.body('{"observations": []}'))
        with patch('verify_staging_delivery.urllib.request.build_opener', return_value=opener):
            with self.assertRaises(state.VerificationError):
                history = get(v.API + '/prints/1/prices')
                v.require(not {7} & {p['id'] for p in history['observations']}, 'Sale observation exposed in public history')
        self.assertEqual(opener.open.call_count, 1)


class SkippedApiBuildTests(unittest.TestCase):
    merge, previous = "m" * 40, "p" * 40
    patterns = ["services/api/**", "deploy/railway/api.Dockerfile"]
    docs = ["docs/agent/handoff/x.md"]

    def decide(self, changed, status, active, unchanged=True):
        return decide_api(self.merge.replace("m", "a"), changed, self.patterns, status,
                          active, lambda sha: unchanged)

    def test_skipped_and_unchanged_passes_with_previous_sha(self):
        self.assertEqual(self.decide(self.docs, "SKIPPED", "b" * 40), ("skip", "b" * 40))

    def test_expected_build_missing_fails(self):
        with self.assertRaises(state.VerificationError):
            self.decide(["services/api/app/main.py"], "SKIPPED", "b" * 40)
        with self.assertRaises(state.VerificationError):
            self.decide(["deploy/railway/api.Dockerfile"], "SKIPPED", "b" * 40)

    def test_unexpected_build_fails(self):
        with self.assertRaises(state.VerificationError):
            self.decide(self.docs, "SUCCESS", "a" * 40)
        with self.assertRaises(state.VerificationError):
            self.decide(self.docs, "SKIPPED", "a" * 40)

    def test_skipped_but_watched_tree_differs_fails(self):
        with self.assertRaises(state.VerificationError):
            self.decide(self.docs, "SKIPPED", "b" * 40, unchanged=False)

    def test_expected_build_waits_for_merge_sha(self):
        self.assertEqual(self.decide(["services/api/app/main.py"], "BUILDING", "b" * 40), ("build", "a" * 40))

    def test_undeterminable_diff_or_patterns_demand_a_build(self):
        self.assertEqual(self.decide(None, None, "b" * 40), ("build", "a" * 40))
        self.assertEqual(decide_api("a" * 40, self.docs, [], None, "b" * 40, lambda s: True), ("build", "a" * 40))
        self.assertEqual(decide_api("a" * 40, self.docs, ["!docs/**"], None, "b" * 40, lambda s: True), ("build", "a" * 40))

    def test_no_railway_decision_yet_is_pending_until_deadline(self):
        self.assertEqual(self.decide(self.docs, None, "b" * 40), ("pending", None))
        live = {"railway": {"services": [{"name": "optcg-price-tracker", "git_sha": "b" * 40}]}}
        with patch.object(state, "sanitize", side_effect=lambda e: e):
            with self.assertRaises(state.VerificationError):
                resolve_api_sha("a" * 40, 0, collect=lambda: live, status=lambda m: None,
                                patterns=lambda: self.patterns, changed=lambda m: self.docs,
                                unchanged=lambda m, w: (lambda s: True), clock=lambda: 1, sleep=Mock())
            result = resolve_api_sha("a" * 40, 10, collect=lambda: live, status=lambda m: "SKIPPED",
                                     patterns=lambda: self.patterns, changed=lambda m: self.docs,
                                     unchanged=lambda m, w: (lambda s: True), clock=lambda: 1, sleep=Mock())
        self.assertEqual((result["mode"], result["sha"], result["watched_changes"]), ("skip", "b" * 40, []))


class ComponentEnvTests(unittest.TestCase):
    def test_resolved_api_sha_is_exported_to_checks(self):
        with patch("verify_staging_delivery.subprocess.run") as run:
            run_component_checks(["scripts/verify_snkr_published_discovery_component.py"], "d" * 40)
        self.assertEqual(run.call_args.kwargs["env"]["STAGING_RESOLVED_API_SHA"], "d" * 40)


if __name__ == '__main__':
    unittest.main()
