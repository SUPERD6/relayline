"""Execution receipts must expose acceptance evidence without changing execution fields."""
import json
from pathlib import Path
import re
import sys

import pytest

from ccx import leadview, ui
from ccx.config import Paths

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ccx import Env
from test_ui import pieces, put_run


@pytest.mark.parametrize('check', [None, {'passed': None}, {'passed': True, 'weak': True},
                                  {'passed': True, 'covers_unknown': True},
                                  {'passed': True, 'basis_changed': ['test_x.py']}])
def test_without_independent_evidence_is_unverified(check):
    assert leadview.receipt_headline({'ok': True, 'status': 'done', 'check': check}) == 'UNVERIFIED'


@pytest.mark.parametrize(('extra', 'expected'), [
    ({'review': {'verdict': 'pass'}}, 'DONE'),
    ({'review': {'verdict': 'pass', 'downgraded': True}}, 'UNVERIFIED'),
    ({'review': {'verdict': 'unknown'}}, 'UNVERIFIED'),
    ({'check': {'passed': True, 'basis': 'self-authored'}}, 'SELF_CHECKED'),
])
def test_review_and_self_check_evidence(extra, expected):
    assert leadview.receipt_headline({'ok': True, 'status': 'done', **extra}) == expected


@pytest.mark.parametrize('kind', ['review_failed', 'review_issues', 'no_answer', 'no_changes', 'env'])
def test_stored_execution_ok_does_not_override_rejected_kind(kind):
    record = {'ok': True, 'kind': kind, 'attempts': [], 'state': 'finished',
              'result': {'status': 'done'}, 'check': {'passed': True}}
    assert leadview.record_headline(record) == 'FAILED'
    assert record['ok'] is True


@pytest.mark.parametrize('extra', [
    {'edited_tests': ['tests/test_existing.py']},
    {'namecheck': ['undefined name: x']},
    {'namecheck': {'hits': [{'name': 'x'}]}},
])
def test_edited_tests_and_namecheck_hits_do_not_support_done(extra):
    receipt = {'ok': True, 'status': 'done', 'check': {'passed': True}, **extra}
    assert leadview.receipt_headline(receipt) == 'UNVERIFIED'


def test_empty_namecheck_hits_do_not_reject_a_passing_check():
    assert leadview.receipt_headline({'ok': True, 'status': 'done', 'check': {'passed': True},
                                     'namecheck': {'hits': []}}) == 'DONE'


def test_record_detection_uses_attempts_not_state():
    stored = {'ok': True, 'attempts': [], 'result': {'status': 'done'}, 'check': {'passed': True}}
    assert leadview.with_headline(stored)['headline'] == 'DONE'
    compact = {'ok': True, 'status': 'done', 'state': 'metadata', 'check': {'passed': True}}
    assert leadview.with_headline(compact)['headline'] == 'DONE'


def test_ui_keeps_workflow_styles_soft_qualifier_and_human_verdict_priority():
    js = (ui.STATIC / 'app.js').read_text(encoding='utf-8')
    status = js.split('function statusHTML(p) {', 1)[1].split('function workflowStatusHTML(p)', 1)[0]
    workflow = js.split('function workflowStatusHTML(p) {', 1)[1].split('function pieceHTML(p, base)', 1)[0]
    assert 'verdict.ok != null && !verdict.soft' in status
    assert status.index('return workflowStatusHTML(judged)') < status.index('const evidence =')
    assert 'receipt_verdict_pass' in status and 'receipt_verdict_fail' in status
    assert 'return workflowStatusHTML(p) + evidence' in status
    assert 'p.headline !== "DONE"' in status
    assert 'verdict.soft ? "st_done_soft" : "st_done"' in workflow
    assert 'class="st pass"' in workflow and 'class="st fail"' in workflow
    strings = json.loads((ui.STATIC / 'strings.json').read_text(encoding='utf-8'))
    for language in ('en', 'zh'):
        assert strings[language]['receipt_verdict_pass']
        assert strings[language]['receipt_verdict_fail']


class TestIssue283(Env):
    def test_ui_command_exports_unverified_receipt_outside_repository(self):
        (self.work / '.git').mkdir()
        put_run(self.hub, 'unverified', self.work)
        snapshot = self.work / 'snapshot.html'
        result = self.ccx('ui', '--project', str(self.work), '--export', str(snapshot))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        page = snapshot.read_text(encoding='utf-8')
        data = json.loads(re.search(r'id="ccx-snapshot">(.*?)</script>', page, re.S).group(1))
        self.assertEqual(pieces(data)[0]['headline'], 'UNVERIFIED')

    def test_checked_any_output_retains_headline_after_line_rendering(self):
        result = self.ccx('run', '--from', 'user', '--to', 'codex', '--model', 'gpt-6-luna',
                          '--effort', 'low', '--mode', 'read', '--no-ab', '--review', 'off',
                          '--check', 'python -c pass', 'Read the parser')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        out = json.loads(result.stdout)
        shown = self.ccx('show', out['run_id'], '--any', env={'CCX_LEAD_VIEW': 'line'})
        self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        self.assertEqual(json.loads(shown.stdout)['finished'][0]['headline'], 'DONE')

    def test_run_and_show_expose_unverified_without_changing_execution(self):
        result = self.ccx('run', '--from', 'user', '--to', 'codex', '--model', 'gpt-6-luna',
                          '--effort', 'low', '--mode', 'read', '--no-ab', '--review', 'off',
                          'Read the parser')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out['headline'], 'UNVERIFIED')
        self.assertTrue(out['ok'])
        self.assertEqual(out['status'], 'done')
        for args in [(), ('--wait', '0'), ('--full',), ('--wait', '0', '--full')]:
            shown = self.ccx('show', out['run_id'], *args)
            self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
            decoded = json.JSONDecoder().raw_decode(shown.stdout)[0]
            self.assertEqual(decoded['headline'], 'UNVERIFIED', args)
        shown = self.ccx('show', out['run_id'], '--any')
        self.assertEqual(json.loads(shown.stdout)['finished'][0]['headline'], 'UNVERIFIED')

    def test_ui_exposes_evidence_separately_from_existing_status(self):
        p = Paths(self.hub)
        rec = put_run(self.hub, 'unverified', self.work)
        rd = ui.Reader(p)
        self.assertEqual(ui.piece_of_run(rd, rec, None, rec['ts'], 'task')['headline'], 'UNVERIFIED')
        self.assertEqual(ui.receipt_row(rd, p, rec, None, {})['headline'], 'UNVERIFIED')
        self.assertEqual(ui._run_row(rd, rec)['headline'], 'UNVERIFIED')
        rec['check'] = {'cmd': 'pytest', 'passed': True, 'exit': 0}
        self.assertEqual(ui._run_row(rd, rec)['headline'], 'DONE')
        rec['check']['covers'] = {'self_authored': True}
        self.assertEqual(ui._run_row(rd, rec)['headline'], 'SELF_CHECKED')
