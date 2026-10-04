import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_staging_delivery import validate_state, get, state


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


if __name__ == '__main__':
    unittest.main()
