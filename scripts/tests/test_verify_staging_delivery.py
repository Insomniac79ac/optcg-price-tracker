import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_staging_delivery import validate_state, get, state, wait_for_delivery


class VerificationTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
