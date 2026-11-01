"""Opt-in roles: real CLI wiring from outside the repo, fake agent binaries only."""
import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from unittest import mock

import pytest

from ccx import board, cli, ledger, plan, report, roles, ui
from ccx.config import Paths, load_config
from test_ccx import Env
from test_ui_runs import fixture_run, request, server  # noqa: F401 - reuse #233 HTTP fixtures


def configure(p, root, value='codex:gpt-6.1-sol:auto', defaults=''):
    f = root / '.ccx' / 'roles.toml'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f'[roles]\nbuild = "{value}"\n' + defaults, encoding='utf-8')
    return f


@pytest.fixture
def project(tmp_path):
    p = Paths(tmp_path / 'hub')
    root = tmp_path / 'project'
    (root / '.git').mkdir(parents=True)
    return p, root


def test_global_project_merge_and_sources(project):
    p, root = project
    p.user_tiers.parent.mkdir(parents=True)
    p.user_tiers.write_text('[roles]\nbuild="codex:gpt-6.1-sol:auto"\nreview="other:auto"\n'
        '[roles.defaults.build]\nmode="write"\nworktree=true\nreview="on"\ncheck="python -m unittest"\n', encoding='utf-8')
    local = configure(p, root, 'codex:gpt-6.1-terra:auto', '[roles.defaults.build]\nreview="off"\n')
    nested = root / 'src'
    nested.mkdir()
    rows = {r['name']: r for r in roles.table(p, nested)['roles']}
    assert rows['build']['model'] == 'gpt-6.1-terra'
    assert rows['build']['defaults'] == dict(mode='write', worktree=True, review='off', check='python -m unittest')
    assert rows['build']['source'] == str(local)
    assert rows['build']['default_sources']['review'] == str(local)
    assert rows['build']['default_sources']['check'] == str(p.user_tiers)
    assert rows['review']['agent'] == 'other' and rows['review']['effort'] == 'auto'
    assert rows['review']['source'] == str(p.user_tiers)


@pytest.mark.parametrize('tier,effort', [('T1', 'low'), ('T2', 'medium'), ('T3', 'high'), ('T4', 'xhigh')])
def test_auto_effort_preserves_model_in_every_tier(project, tier, effort):
    p, root = project
    configure(p, root)
    cfg = load_config(p)
    def ordinary(spec, caller, p, cfg):
        assert spec['to'] == 'codex' and spec['model'] is None
        return {'to': 'codex', 'tier': tier}, {'source': 'keywords', 'tier': tier}
    kw, route = plan.resolve_role({'role': 'build', 'cwd': str(root)}, 'claude', p, cfg, ordinary)
    assert (kw['model'], kw['effort']) == ('gpt-6.1-sol', effort)
    assert route['role_effort_auto'] and route['role'] == 'build'


def test_rubric_effort_and_stale_estimates_are_not_reused(project):
    p, root = project
    configure(p, root)
    def ordinary(*args):
        return {'to': 'codex', 'tier': 'auto', 'model': 'gpt-6-astra', 'effort': 'xhigh'}, {
            'b': 8, 'rung': 'codex:gpt-6-astra:xhigh', 'expected_usd': 4, 'p': .9, 'chain_p': .99}
    kw, route = plan.resolve_role({'role': 'build', 'cwd': str(root), 'b': 8}, 'claude', p, load_config(p), ordinary)
    assert kw['model'] == 'gpt-6.1-sol' and kw['effort'] == 'xhigh'
    assert 'expected_usd' not in route and 'p' not in route and route['b'] == 8


def test_model_auto_uses_existing_route_and_explicit_flags_win(project):
    p, root = project
    configure(p, root, 'codex:auto:auto')
    ordinary = mock.Mock(return_value=(None, {'advice': 'do-it-yourself'}))
    kw, route = plan.resolve_role({'role': 'build', 'cwd': str(root)}, 'claude', p, load_config(p), ordinary)
    assert kw is None and route['advice'] == 'do-it-yourself'
    assert not ordinary.call_args.args[0].get('force')
    configure(p, root, defaults='[roles.defaults.build]\nmode="write"\nworktree=true\nreview="on"\ncheck="default"\n')
    a = cli.parse(['run', '--role', 'build', '--model', 'opus', '--effort', 'max', '--to', 'claude',
                   '--mode', 'read', '--no-worktree', '--review', 'off', '--check', 'override', 'a task'])
    roles.apply_defaults(a, roles.get(p, root, 'build'))
    assert (a.mode, a.worktree, a.review, a.check) == ('read', False, 'off', 'override')
    def picked(spec, *args):
        assert spec['to'] == 'claude'
        return {'to': 'claude', 'tier': 'T2'}, {}
    kw, route = plan.resolve_role({'role': 'build', 'cwd': str(root), 'to': a.to, 'model': a.model,
        'effort': a.effort, 'explicit': a._explicit}, 'user', p, load_config(p), picked)
    assert (kw['to'], kw['model'], kw['effort']) == ('claude', 'opus', 'max')
    assert not route['role_effort_auto']


def test_no_role_calls_resolver_unchanged(project):
    p, root = project
    spec = {'brief': 'a task', 'cwd': str(root)}
    expected = ({'to': 'codex'}, {'source': 'old'})
    ordinary = mock.Mock(return_value=expected)
    assert plan.resolve_role(spec, 'claude', p, load_config(p), ordinary) is expected
    assert ordinary.call_args.args[0] is spec


def test_other_cross_vendor_and_same_vendor_different_model(project):
    p, root = project
    f = configure(p, root)
    f.write_text(f.read_text(encoding='utf-8') + 'review="other:auto"\n', encoding='utf-8')
    cfg = load_config(p)
    def picked(spec, *args):
        return {'to': spec['to'], 'tier': 'T2'}, {}
    with mock.patch('ccx.agents.others', return_value=['claude']):
        kw, route = plan.resolve_role({'role': 'review', 'cwd': str(root)}, 'claude', p, cfg, picked)
        assert kw['to'] == 'claude' and 'role_fallback' not in route
    with mock.patch('ccx.agents.others', return_value=[]), mock.patch('ccx.runners.find_bin', return_value='fake'):
        kw, route = plan.resolve_role({'role': 'review', 'cwd': str(root)}, 'claude', p, cfg, picked)
        assert kw['to'] == 'codex' and kw['model'] != 'gpt-6.1-sol'
        assert 'same vendor, different model' in route['role_fallback']
        assert 'other:' in roles.receipt(route)


@pytest.mark.parametrize('name', ['../escape', '', 'defaults', 'a/b', '-x'])
def test_role_names_cannot_escape_template_directory(project, name):
    p, root = project
    with pytest.raises(ValueError):
        roles.get(p, root, name)


class TestRoleCommands(Env):
    def json(self, *args):
        r = self.ccx(*args)
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)

    def test_roles_set_show_unset_and_arbitrary_names(self):
        self.json('roles', 'set', 'build', 'codex:gpt-6.1-sol:auto')
        self.json('roles', 'set', 'fix', 'claude:opus:high')
        before = (self.hub / 'ccx' / 'tiers.toml').read_text(encoding='utf-8')
        self.json('roles', 'set', 'build', 'codex:gpt-6.1-terra:auto', '--project')
        merged = {r['name']: r for r in self.json('roles')['roles']}
        assert merged['build']['model'] == 'gpt-6.1-terra' and merged['fix']['agent'] == 'claude'
        self.json('roles', 'unset', 'build', '--project')
        assert self.json('roles', 'show')['roles'][0]['model'] == 'gpt-6.1-sol'
        self.json('roles', 'unset', 'fix')
        assert len(self.json('roles')['roles']) == 1
        assert 'fix' in before

    def test_run_role_template_defaults_override_and_receipt(self):
        p = Paths(self.hub)
        configure(p, self.work, defaults='[roles.defaults.build]\nmode="write"\nreview="off"\ncheck="python -m unittest"\n')
        template = self.work / '.ccx' / 'briefs' / 'templates' / 'build.md'
        template.parent.mkdir(parents=True)
        template.write_text('# Build\n{task}\nOnly change parser.py', encoding='utf-8')
        out = self.json('run', '--role', 'build', '--tier', 'T3', '--check', 'python -c pass',
                        '--no-escalate', '--no-fallback', '--from', 'user', 'Implement a parser')
        assert out['role'] == 'build' and out['model'] == 'gpt-6.1-sol/high'
        assert 'high（按难度）' in out['role_receipt']
        rec = ledger.load_run(p, out['run_id'])
        assert rec['role'] == 'build' and rec['mode'] == 'write' and rec['check_cmd'] == 'python -c pass'
        assert ledger.rows(p)[-1]['role'] == 'build'
        prompt = self.calls()[-1]['prompt']
        assert '# Build\nImplement a parser' in prompt and '{task}' not in prompt
        assert str(self.work / 'AGENTS.md') in prompt and 'Only change parser.py' in prompt
        assert 'python -m unittest' not in (p.runs / out['run_id'] / 'brief.md').read_text(encoding='utf-8')
        summary = report.summarize(p, report.collect(p, include_lead=False))
        assert summary['runs'][0]['role'] == 'build' and summary['roles'][0]['runs'] == 1
        assert '<th>role</th>' in report.render_html(summary)

    def test_route_and_run_agree_on_effort(self):
        configure(Paths(self.hub), self.work)
        route = self.json('route', '--role', 'build', '--b', '5', 'Implement a parser')
        run = self.json('run', '--role', 'build', '--b', '5', '--mode', 'read', '--review', 'off',
                        '--no-escalate', '--no-fallback', '--from', 'user', 'Implement a parser')
        assert route['rung'] == run['route']['rung']
        assert '强度按难度' in route['role_note']

    def test_empty_config_keeps_null_role_in_record_only(self):
        assert self.json('roles')['roles'] == []
        out = self.json('run', '--to', 'codex', '--tier', 'T1', '--mode', 'read', 'Read the parser')
        assert 'role' not in out and 'role_receipt' not in out
        assert ledger.load_run(Paths(self.hub), out['run_id'])['role'] is None

    def test_terra_alias_is_passed_to_fake_cli(self):
        from ccx.agents.codex import KNOWN_MODELS
        assert 'gpt-6.1-terra' in KNOWN_MODELS
        configure(Paths(self.hub), self.work, 'codex:gpt-6.1-terra:auto')
        out = self.json('run', '--role', 'build', '--tier', 'T2', '--mode', 'read', '--review', 'off',
                        '--no-escalate', '--no-fallback', 'Read the parser')
        assert out['model'] == 'gpt-6.1-terra/medium'
        assert 'gpt-6.1-terra' in self.calls()[-1]['argv']

    def marker_check(self, name):
        script = self.work / f'{name}.py'
        script.write_text(f'from pathlib import Path\nPath("{name}.marker").write_text("ran", encoding="utf-8")\n',
                          encoding='utf-8')
        return f'"{sys.executable}" {script.name}', self.work / f'{name}.marker'

    def test_project_check_is_displayed_but_not_executed(self):
        cmd, marker = self.marker_check('project_check')
        p = Paths(self.hub)
        source = configure(p, self.work, defaults='[roles.defaults.build]\nmode="read"\nreview="off"\n'
            + 'check=' + json.dumps(cmd) + '\n')
        template = self.work / '.ccx' / 'briefs' / 'templates' / 'build.md'
        template.parent.mkdir(parents=True)
        template.write_text('Read: {task}', encoding='utf-8')
        result = self.ccx('run', '--role', 'build', '--tier', 'T2', '--no-escalate', '--no-fallback', 'Read parser')
        assert result.returncode == 0, result.stdout + result.stderr
        out = json.loads(result.stdout)
        rec = ledger.load_run(p, out['run_id'])
        assert rec['check_cmd'] is None and not marker.exists()
        assert str(source) in out['role_receipt'] and '不自动采用' in out['role_receipt']
        assert str(source) in result.stderr
        row = self.json('roles')['roles'][0]
        assert row['defaults']['check'] == cmd and row['default_sources']['check'] == str(source)
        assert 'check' not in row['effective_defaults']
        assert cmd not in (p.runs / out['run_id'] / 'brief.md').read_text(encoding='utf-8')

    def test_global_check_remains_effective_when_project_overrides_check(self):
        global_cmd, global_marker = self.marker_check('global_check')
        project_cmd, project_marker = self.marker_check('project_check')
        p = Paths(self.hub)
        p.user_tiers.parent.mkdir(parents=True)
        p.user_tiers.write_text('[roles.defaults.build]\ncheck=' + json.dumps(global_cmd) + '\n', encoding='utf-8')
        configure(p, self.work, defaults='[roles.defaults.build]\nmode="read"\nreview="off"\n'
            + 'check=' + json.dumps(project_cmd) + '\n')
        out = self.json('run', '--role', 'build', '--tier', 'T2', '--no-escalate', '--no-fallback', 'Read parser')
        assert ledger.load_run(p, out['run_id'])['check_cmd'] == global_cmd
        assert global_marker.exists() and not project_marker.exists()
        row = self.json('roles')['roles'][0]
        assert row['effective_defaults']['check'] == global_cmd
        assert row['effective_default_sources']['check'] == str(p.user_tiers)

    def test_explicit_check_can_use_reviewed_project_command(self):
        cmd, marker = self.marker_check('project_check')
        p = Paths(self.hub)
        configure(p, self.work, defaults='[roles.defaults.build]\nmode="read"\nreview="off"\n'
            + 'check=' + json.dumps(cmd) + '\n')
        out = self.json('run', '--role', 'build', '--tier', 'T2', '--check', cmd,
                        '--no-escalate', '--no-fallback', 'Read parser')
        assert ledger.load_run(p, out['run_id'])['check_cmd'] == cmd and marker.exists()

    def test_model_auto_failure_escalates_to_next_tier(self):
        configure(Paths(self.hub), self.work, 'codex:auto:auto')
        result = self.ccx('run', '--role', 'build', '--tier', 'T1', '--mode', 'read', '--review', 'off',
                          '--no-fallback', 'Read parser', env={'FAKE_STATUS': 'blocked_then_done'})
        assert result.returncode == 0, result.stdout + result.stderr
        rec = ledger.load_run(Paths(self.hub), json.loads(result.stdout)['run_id'])
        assert [a['rung'] for a in rec['attempts']] == ['codex:gpt-6-luna:low', 'codex:gpt-6.1-sol:medium']
        assert not rec['route'].get('role_fixed_model')

    def test_fixed_model_real_run_is_not_marked_no_ab_or_excluded_from_ability(self):
        from ccx import ability
        p = Paths(self.hub)
        configure(p, self.work)
        out = self.json('run', '--role', 'build', '--tier', 'T1', '--mode', 'read', '--review', 'off', 'Read parser')
        rec = ledger.load_run(p, out['run_id'])
        assert 'no_ab' not in rec['route'] and 'no_ab' not in ledger.rows(p)[-1]
        self.json('verify', out['run_id'], '--ok', '1')
        assert any(r['model'] == 'gpt-6.1-sol' and r['n'] == 1 for r in ability.table(p, persist=False)['rows'])
        excluded = self.json('run', '--role', 'build', '--tier', 'T1', '--mode', 'read', '--review', 'off',
                             '--no-ab', '--new', 'Read another parser')
        assert ledger.load_run(p, excluded['run_id'])['route']['no_ab']
        assert ledger.is_eval(ledger.runs_by_id(ledger.rows(p))[excluded['run_id']])

    def test_project_role_set_unset_preserves_all_unrelated_bytes_and_array_keys(self):
        source = configure(Paths(self.hub), self.work)
        prefix = '# unrelated header\r\ntitle = "keep"\r\n'
        role = '[roles]\r\nbuild = "codex:gpt-6.1-sol:auto"\r\n[roles.defaults.build]\r\nreview = "off"\r\n'
        rest = '[[tools]]\r\nbuild = "tool-value"\r\n# keep formatting\r\n[[jobs]]\r\nbuild="job-value"'
        before = (prefix + role + rest).encode('utf-8')
        source.write_bytes(before)
        for args in (('set', 'build', 'codex:gpt-6.1-terra:auto'), ('unset', 'build')):
            self.json('roles', *args, '--project')
            after = source.read_bytes()
            assert after.startswith(prefix.encode()) and after.endswith(rest.encode())
            parsed = tomllib.loads(after.decode('utf-8'))
            old = tomllib.loads(before.decode('utf-8'))
            assert {k: v for k, v in parsed.items() if k != 'roles'} == {k: v for k, v in old.items() if k != 'roles'}
            assert parsed['roles']['defaults'] == old['roles']['defaults']
            if args[0] == 'set':
                assert parsed['roles']['build'] == args[2]
            else:
                assert 'build' not in parsed['roles']

    def test_abbreviated_explicit_check_overrides_global_role_default_and_is_recorded_canonically(self):
        default, default_marker = self.marker_check('default_check')
        explicit, explicit_marker = self.marker_check('explicit_check')
        p = Paths(self.hub)
        p.user_tiers.parent.mkdir(parents=True)
        p.user_tiers.write_text('[roles]\nbuild="codex:gpt-6.1-sol:auto"\n[roles.defaults.build]\ncheck='
                               + json.dumps(default) + '\n', encoding='utf-8')
        out = self.json('run', '--role', 'build', '--tier', 'T1', '--mode', 'read', '--review', 'off',
                        '--che', explicit, 'Read parser')
        rec = ledger.load_run(p, out['run_id'])
        assert rec['check_cmd'] == explicit and explicit_marker.exists() and not default_marker.exists()
        assert '--check' in rec['route']['explicit_flags'] and '--che' not in rec['route']['explicit_flags']

    def test_worktree_role_record_keeps_source_checkout(self):
        for args in (('init', '-q'), ('config', 'user.name', 'test'), ('config', 'user.email', 'test@example.com')):
            subprocess.run(['git', *args], cwd=self.work, check=True, capture_output=True)
        (self.work / '.gitignore').write_text('.ccx/\n', encoding='utf-8')
        (self.work / 'a.txt').write_text('base', encoding='utf-8')
        subprocess.run(['git', 'add', '-A'], cwd=self.work, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-qm', 'fixture'], cwd=self.work, check=True, capture_output=True)
        configure(Paths(self.hub), self.work)
        self.env['FAKE_WRITE'] = 'a.txt=changed by fake build'
        out = self.json('run', '--role', 'build', '--tier', 'T1', '--worktree', '--mode', 'write', '--review', 'off',
                        '--no-escalate', '--no-fallback', 'Edit a.txt')
        rec = ledger.load_run(Paths(self.hub), out['run_id'])
        assert Path(rec['source_cwd']) == self.work.resolve() and Path(rec['cwd']) != self.work.resolve()
        assert roles.repository(Path(rec['cwd'])) == roles.repository(self.work)


def test_template_no_template_and_literal_braces(project):
    p, root = project
    configure(p, root)
    assert roles.brief(p, root, 'build', 'task') == 'task'
    f = root / '.ccx' / 'briefs' / 'templates' / 'build.md'
    f.parent.mkdir(parents=True)
    f.write_text('{task}\nJSON example: {"a": 1}', encoding='utf-8')
    text = roles.brief(p, root, 'build', 'task {task}')
    assert text.startswith('task {task}\nJSON example: {"a": 1}')


def test_task_text_after_separator_does_not_override_role_defaults(project):
    p, root = project
    configure(p, root, defaults='[roles.defaults.build]\nreview="on"\n')
    a = cli.parse(['run', '--role', 'build', '--', '--review'])
    roles.apply_defaults(a, roles.get(p, root, 'build'))
    assert a.review == 'on' and a.brief == ['--review']


def test_roles_api_read_only_and_role_two_step_confirmation(server, monkeypatch):
    srv, p, root = server
    configure(p, root, defaults='[roles.defaults.build]\nmode="write"\nreview="on"\n')
    template = root / '.ccx' / 'briefs' / 'templates' / 'build.md'
    template.parent.mkdir(parents=True)
    template.write_text('Build: {task}', encoding='utf-8')
    before = {str(f): f.read_bytes() for f in root.rglob('*') if f.is_file()}
    code, data = request(srv, '/api/roles?project=' + ui._pid(root))
    assert code == 200 and data['roles'][0]['name'] == 'build'
    assert before == {str(f): f.read_bytes() for f in root.rglob('*') if f.is_file()}
    assert request(srv, '/api/roles', {'build': 'claude:opus:high'})[0] == 404
    assert request(srv, '/api/roles', token=False)[0] == 403
    monkeypatch.setattr(ui, 'execute_chat', mock.Mock(return_value={'ok': True, 'started': True, 'action': 'fake'}))
    code, preview = request(srv, '/api/chat/prepare', {'project': ui._pid(root), 'text': 'ccx run --role build add parser'})
    assert code == 200 and preview['nonce'] and 'Build: add parser' in preview['brief']
    assert preview['argv'][preview['argv'].index('--mode') + 1] == 'write'
    ui.execute_chat.assert_not_called()
    code, result = request(srv, '/api/chat/run', {'nonce': preview['nonce']})
    assert code == 200 and result['started']
    ui.execute_chat.assert_called_once()
    assert request(srv, '/api/chat/run', {'nonce': preview['nonce']})[0] == 409
    assert any(e['via'] == 'ui' for e in board.entries(root))


def test_role_confirmation_invalidated_by_configuration_or_template_change(server):
    srv, p, root = server
    f = configure(p, root)
    code, preview = request(srv, '/api/chat/prepare', {'project': ui._pid(root), 'text': 'ccx run --role build add parser'})
    assert code == 200
    f.write_text('[roles]\nbuild="claude:opus:high"\n', encoding='utf-8')
    with mock.patch.object(ui, 'execute_chat') as execute:
        assert request(srv, '/api/chat/run', {'nonce': preview['nonce']})[0] == 409
        execute.assert_not_called()


def test_role_ui_keeps_allowlist_and_length_limit(server):
    srv, p, root = server
    configure(p, root)
    for text in ('ccx roles set build claude:opus:high', 'ccx run --role missing x',
                 'ccx run --role build --check malicious x', 'x' * 4001):
        assert request(srv, '/api/chat/prepare', {'project': ui._pid(root), 'text': text})[0] == 400


def test_ui_project_check_stays_inert_after_actual_confirmation(server, monkeypatch):
    srv, p, root = server
    marker = root / 'project_check.marker'
    script = root / 'project_check.py'
    script.write_text('from pathlib import Path\nPath("project_check.marker").write_text("ran", encoding="utf-8")\n',
                      encoding='utf-8')
    cmd = f'"{sys.executable}" {script.name}'
    source = configure(p, root, defaults='[roles.defaults.build]\nmode="read"\nreview="off"\n'
        + 'check=' + json.dumps(cmd) + '\n')
    template = root / '.ccx' / 'briefs' / 'templates' / 'build.md'
    template.parent.mkdir(parents=True)
    template.write_text('Read: {task}', encoding='utf-8')
    repo = Path(__file__).resolve().parents[1]
    for name in ('codex', 'claude'):
        monkeypatch.setenv(f'CCX_{name.upper()}_BIN', str(repo / 'tests' / 'fakes' / f'fake_{name}.py'))
    monkeypatch.setenv('CCX_NO_QUOTA_PROBE', '1')
    monkeypatch.setenv('CCX_NO_BENCH_REFRESH', '1')
    monkeypatch.setenv('CCX_AB_RATE', '0')
    code, preview = request(srv, '/api/chat/prepare', {'project': ui._pid(root),
        'text': 'ccx run --role build --tier T2 Read parser'})
    assert code == 200
    assert preview['role']['defaults']['check'] == cmd
    assert 'check' not in preview['role']['effective_defaults']
    assert str(source) in preview['role']['check_notice'] and cmd not in preview['brief']
    code, started = request(srv, '/api/chat/run', {'nonce': preview['nonce']})
    assert code == 200 and started['started']
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        code, result = request(srv, started['result_url'])
        if code == 200 and not result.get('pending'):
            break
        time.sleep(.05)
    else:
        pytest.fail('confirmed UI command did not finish: ' + Path(started['log']).read_text(encoding='utf-8'))
    assert result['ok'], result
    rec = ledger.load_run(p, started['run_id'])
    assert rec['state'] == 'finished' and rec['check_cmd'] is None and not marker.exists()
    assert str(source) in rec['route']['role_check_notice']


def test_ability_role_is_optional_fourth_dimension(project):
    from test_ability import add
    from ccx import ability
    p, root = project
    add(p, 'b1', role='build')
    add(p, 't1', role='test')
    add(p, 'old')
    add(p, 'self', role='build', kind='ok_self_checked')
    for rid in ('b1', 't1', 'old', 'self'):
        ledger.append_event(p, {'type': 'verify', 'run_id': rid, 'ok': True, 'ts': 200})
    before = ability.table(p, persist=False)
    grouped = roles.ability_table(p)
    cells = {r['role']: r for r in grouped['rows']}
    assert set(cells) == {None, 'build', 'test'}
    assert cells['build']['ok'] == 1 and cells['build']['ok_self_checked'] == 1
    assert cells['build']['n'] == 2 and cells[None]['ok'] == 1
    assert len(roles.ability_table(p, role='test')['rows']) == 1
    assert ability.table(p, persist=False) == before
    assert not (p.state / 'ability.json').exists()


def test_quota_gate_still_applies_to_fixed_role(project):
    p, root = project
    configure(p, root)
    def tight(*args):
        return {'to': 'codex', 'tier': 'T2'}, {'quota_routing': {'all_tight': True}, 'advice': 'wait for reset'}
    kw, route = plan.resolve_role({'role': 'build', 'cwd': str(root)}, 'claude', p, load_config(p), tight)
    assert kw is None and route['advice'] == 'wait for reset'


def test_fixed_role_empty_ladder_does_not_restore_another_model(project):
    from ccx.delegate import Request
    p, root = project
    req = Request(to='codex', brief='task', cwd=root, model='gpt-6.1-sol', effort='xhigh',
                  route={'role': 'build', 'role_fixed_model': True, 'ladder': []})
    with mock.patch.object(plan.learn, 'ladder_after') as learned:
        rungs = plan._plan(req, p, load_config(p), 1)
        learned.assert_not_called()
    assert [r['rung'] for r in rungs] == ['codex:gpt-6.1-sol:xhigh']


@pytest.mark.parametrize('layout', ['sibling', 'inside'])
def test_other_uses_actual_build_vendor_across_removed_worktrees(project, layout):
    from ccx.workspace import worktree_path
    p, root = project
    source = configure(p, root)
    source.write_text(source.read_text(encoding='utf-8') + 'review="other:auto:auto"\n', encoding='utf-8')
    old_cwd = worktree_path(root, 'removed-build', layout)
    # Initial dispatch was Codex; the actual final build attempt ran on Claude after a fallback.
    ledger.append_event(p, {'run_id': 'b', 'role': 'build', 'to': 'codex', 'cwd': str(old_cwd),
                            'rungs': ['codex:gpt-6.1-sol:medium', 'claude:opus:high']})
    def picked(spec, *args):
        return {'to': spec['to'], 'tier': 'T2'}, {}
    with mock.patch('ccx.agents.others', return_value=['codex']) as others:
        kw, _ = plan.resolve_role({'role': 'review', 'cwd': str(root)}, 'claude', p, load_config(p), picked)
        others.assert_called_once_with('claude', load_config(p))
    assert kw['to'] == 'codex'


def test_model_auto_resolver_leaves_tier_model_unset(project):
    from ccx.delegate import Request
    p, root = project
    configure(p, root, 'codex:auto:auto')
    def picked(spec, *args):
        return {'to': 'codex', 'tier': 'T1'}, {'tier': 'T1'}
    kw, route = plan.resolve_role({'role': 'build', 'cwd': str(root)}, 'claude', p, load_config(p), picked)
    assert not kw.get('model') and not route.get('role_fixed_model')
    req = Request(brief='Read parser', cwd=root, **kw)
    assert [r['tier'] for r in plan._plan(req, p, load_config(p), 1)] == ['T1', 'T2']


def test_other_uses_recorded_source_and_final_attempt_over_initial_dispatch(project):
    p, root = project
    source = configure(p, root)
    source.write_text(source.read_text(encoding='utf-8') + 'review="other:auto:auto"\n', encoding='utf-8')
    ledger.append_event(p, {'run_id': 'b', 'role': 'build', 'to': 'codex',
                            'cwd': str(root.parent / 'old-custom-worktree'), 'rungs': ['codex:gpt-6.1-sol:medium']})
    d = p.runs / 'b'
    d.mkdir(parents=True)
    ledger.write_record(d, {'role': 'build', 'source_cwd': str(root), 'to': 'codex',
        'attempts': [{'agent': 'claude', 'model': 'opus', 'rung': 'claude:opus:high'}]})
    def picked(spec, *args):
        return {'to': spec['to'], 'tier': 'T2'}, {}
    with mock.patch('ccx.agents.others', return_value=['codex']) as others:
        kw, _ = plan.resolve_role({'role': 'review', 'cwd': str(root)}, 'claude', p, load_config(p), picked)
    assert others.call_args.args[0] == 'claude' and kw['to'] == 'codex'


@pytest.mark.skipif(os.name != 'nt', reason='Windows extended-length path spelling')
def test_role_history_repository_canonicalizes_extended_length_checkout(project):
    p, root = project
    extended = Path('//?/' + root.as_posix())
    with mock.patch.object(roles, 'project_root', return_value=extended):
        assert roles.repository(root) == root


@pytest.mark.parametrize('value', ['1', '0', '"bad"', 'false'])
def test_scalar_global_role_defaults_has_clear_error(project, value):
    p, root = project
    p.user_tiers.parent.mkdir(parents=True)
    p.user_tiers.write_text('[roles]\ndefaults=' + value + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'roles.defaults.*must be a table'):
        roles.table(p, root)


def test_roles_api_parses_each_configuration_document_once(server):
    srv, p, root = server
    configure(p, root)
    p.user_tiers.parent.mkdir(parents=True, exist_ok=True)
    p.user_tiers.write_text('[roles.defaults.build]\nreview="off"\n', encoding='utf-8')
    with mock.patch.object(roles, 'load_config', wraps=load_config) as load, \
            mock.patch.object(roles, '_read', wraps=roles._read) as read:
        code, data = request(srv, '/api/roles?project=' + ui._pid(root))
    assert code == 200 and data['roles'][0]['defaults']['review'] == 'off'
    load.assert_called_once()
    assert read.call_args_list == [mock.call(root / '.ccx' / 'roles.toml')]


@pytest.mark.skipif(not os.environ.get('CCX_UI_BROWSER'), reason='set CCX_UI_BROWSER for role button browser smoke')
def test_browser_role_buttons_prefill_preview_and_confirm(server, tmp_path):
    from test_ui_runs import HeadlessBrowser
    srv, p, root = server
    srv.demo = True                         # second click exercises the guard; no paid CLI can be started
    configure(p, root, defaults='[roles.defaults.build]\nmode="write"\nreview="on"\n')
    template = root / '.ccx' / 'briefs' / 'templates' / 'build.md'
    template.parent.mkdir(parents=True)
    template.write_text('Build: {task}', encoding='utf-8')
    browser = HeadlessBrowser(os.environ['CCX_UI_BROWSER'], tmp_path / 'role-browser')
    try:
        browser.call('Page.navigate', {'url': srv.url})
        browser.wait_for('!!document.querySelector("[data-chat-role=build]")')
        browser.evaluate('document.querySelector("#chat-input").value = "Implement parser"; '
            'document.querySelector("#chat-input").dispatchEvent(new Event("input", {bubbles:true})); '
            'document.querySelector("[data-chat-role=build]").click();')
        assert browser.evaluate('document.querySelector("#chat-input").value') == 'ccx run --role build -- "Implement parser"'
        assert not srv.chats and not any(r.get('type') == 'ui_command' for r in ledger.rows(p))
        browser.evaluate('document.querySelector("[data-chat=preview]").click()')
        browser.wait_for('!!document.querySelector("[data-chat=confirm]")')
        assert browser.evaluate('document.querySelector(".ui-chat .cmd").textContent.includes("Build: Implement parser")')
        assert not any(r.get('type') == 'ui_command' for r in ledger.rows(p))
        browser.evaluate('document.querySelector("[data-chat=confirm]").click()')
        browser.wait_for('!!document.querySelector(".ui-chat [role=status]") && !document.querySelector("[data-chat=confirm]")')
        assert not any(r.get('type') == 'ui_command' for r in ledger.rows(p))
    finally:
        browser.close()


@pytest.mark.skipif(not os.environ.get('CCX_UI_BROWSER'), reason='set CCX_UI_BROWSER for project check preview smoke')
def test_browser_project_check_notice_and_effective_defaults(server, tmp_path):
    from test_ui_runs import HeadlessBrowser
    srv, p, root = server
    srv.demo = True
    source = configure(p, root, defaults='[roles.defaults.build]\ncheck="echo untrusted-project-check"\n')
    browser = HeadlessBrowser(os.environ['CCX_UI_BROWSER'], tmp_path / 'project-check-browser')
    try:
        browser.call('Page.navigate', {'url': srv.url})
        browser.wait_for('!!document.querySelector("[data-chat-role=build]")')
        browser.evaluate('document.querySelector("#chat-input").value = "Read parser"; '
            'document.querySelector("#chat-input").dispatchEvent(new Event("input", {bubbles:true})); '
            'document.querySelector("[data-chat-role=build]").click(); '
            'document.querySelector("[data-chat=preview]").click();')
        browser.wait_for('!!document.querySelector(".ui-chat .cmd [role=note]")')
        notice = browser.evaluate('document.querySelector(".ui-chat .cmd [role=note]").textContent')
        assert str(source) in notice and '不自动采用' in notice
        assert not browser.evaluate('document.querySelector(".ui-chat .cmd").textContent.includes("untrusted-project-check")')
    finally:
        browser.close()
