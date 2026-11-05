"""Result labels are presentation only; fake CLIs and no model calls."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ccx import leadview

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ccx import Env, ROOT


@pytest.mark.parametrize(('extra', 'headline'), [
    ({'kind': 'check_failed', 'check': {'passed': False}}, 'CHECK_FAILED'),
    ({'check': {'passed': False}}, 'CHECK_FAILED'),
    ({'kind': 'check_broken', 'check': {'passed': False}}, 'CHECK_BROKEN'),
    ({'check': {'passed': None, 'status': 'check_broken'}}, 'CHECK_BROKEN'),
    ({'status': 'partial'}, 'PARTIAL'),
    ({'status': 'blocked'}, 'BLOCKED'),
    ({'max_usd': {'cap': 1}}, 'STOPPED'),
    ({'review': {'verdict': 'issues'}}, 'REVIEW_ISSUES'),
    ({'review': {'verdict': 'not-run'}}, 'PARTIAL'),
    ({'kind': 'ok_self_checked'}, 'SELF_CHECKED'),
    ({'check': None}, 'UNVERIFIED'),
    ({'ok': False}, 'FAILED'),
    ({}, 'DONE'),
])
def test_compact_headline_preserves_existing_fields(extra, headline):
    receipt = {'run_id': 'r', 'ok': True, 'status': 'done', 'check': {'passed': True}, **extra}
    original = dict(receipt)
    encoded = leadview.dumps(receipt, True)
    assert encoded.startswith('{"headline":"' + headline + '"')
    result = json.loads(encoded)
    assert result.pop('headline') == headline
    assert result == original == receipt
    assert len(encoded.splitlines()) == 1
    assert json.loads(leadview.dumps(receipt, False)) == original


def test_serializing_again_recomputes_a_stale_headline():
    receipt = {'headline': 'DONE', 'ok': True, 'status': 'partial', 'check': {'passed': False}}
    encoded = leadview.dumps(receipt, True)
    assert encoded.startswith('{"headline":"CHECK_FAILED"')
    assert leadview.dumps(json.loads(encoded), True) == encoded
    assert receipt['headline'] == 'DONE'


class TestReceiptCommand(Env):
    def test_p4_failed_check_is_first_despite_ok_true_outside_repository(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/eval/p4_receipt.py'), 'run', '--from', 'user',
             '--to', 'codex', '--model', 'gpt-6-luna', '--effort', 'low', '--mode', 'read',
             '--no-ab', '--no-escalate', '--no-fallback', '--review', 'off',
             '--check', 'python -c "raise SystemExit(1)"', 'Read the parser'],
            cwd=self.work, env={**self.env, 'CCX_P4_ROOT': str(ROOT), 'FAKE_STATUS': 'partial'},
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith('{"headline":"CHECK_FAILED"'), result.stdout)
        out = json.loads(result.stdout)
        self.assertTrue(out['ok'])
        self.assertEqual(out['status'], 'partial')
        self.assertFalse(out['check']['passed'])
        self.assertEqual(len(result.stdout.splitlines()), 1)
        whole = json.loads(self.ccx('show', out['run_id']).stdout)
        self.assertEqual(whole['kind'], 'check_failed')
        self.assertTrue(whole['ok'])

    def test_native_compact_output_starts_with_done(self):
        result = self.ccx('run', '--from', 'user', '--to', 'codex', '--model', 'gpt-6-luna',
                          '--effort', 'low', '--mode', 'read', '--no-ab', '--review', 'off',
                          '--check', 'python -c pass', 'Read the parser', env={'CCX_LEAD_VIEW': 'line'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith('{"headline":"DONE"'), result.stdout)
        self.assertEqual(json.loads(result.stdout)['view'], 'line')
