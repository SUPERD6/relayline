# Credential-free newcomer walkthrough — 2026-11-05

English · [中文](2026-11-05-walkthrough.zh.md)

Evidence: **engineering check**, relayline 0.6.0 working tree, Windows, Python 3.11. No real agent CLI, model, account or credential was used. This is one scripted walkthrough, not a user study or a performance comparison.

## Reproduce

From any directory, run `python <checkout>/scripts/walkthrough.py`. It creates and retains a new temporary directory, prints its location and writes `result.json`, `logs/*.stdout.txt`, `logs/*.stderr.txt`, fake call records and HTML exports there. It uses only the standard library, including `venv`; the editable package build needs setuptools >=77 and wheel.

Offline installation: `python <checkout>/scripts/walkthrough.py --wheelhouse <directory-of-build-wheels>`. With explicit permission to access public PyPI: `python <checkout>/scripts/walkthrough.py --allow-download`. No network is used by default. Build dependency availability is separate from relayline's zero runtime dependencies.

All ccx child processes run in the new temporary work directory, outside the checkout. HOME, USERPROFILE, CCX_HUB, CCX_CONFIG, tool homes, application-data directories and temporary directories point into that new directory. An environment allowlist drops inherited credentials, CLI overrides, lead identities and Python/pip configuration. PATH contains only private fake launchers and the temporary venv; automatic app discovery is disabled. Only named package inputs are copied; local repository state is not traversed. The original checkout and real tool homes/hub are not used as runtime state.

## Observations

| Step | Result | Friction / evidence boundary |
|---|---|---|
| Fresh venv | Pass | Isolated Python environment created. |
| `pip install -e` | Fail | Public build dependency download was blocked by the sandbox (WinError 10013). Offline retry also lacks setuptools >=77. No cached build wheels were available. Installed-package behavior is **Unknown**. |
| `ccx setup` with piped stdin | Pass using source fallback | Prints the plan and `Nothing was changed.`; no user-config file was created. Piped setup is a preview, which can surprise a person expecting installation to finish. |
| `ccx setup --yes` | Pass using source fallback | Creates isolated hub/wiring and exercises both fake selftests. `--yes` also accepts the paid selftest on real installations; this script only exposes fake tools. Hook trust is still a manual client step. |
| `ccx doctor` | Pass using source fallback | Fake versions and login probes work. Codex 0.163 fake versus adapter-tested 0.164 produces a version warning; subscription quota remains Unknown. Login success is simulated. |
| `ccx demo --no-open --export ...` | Pass using source fallback | Generates a populated static page; no browser or server opened. Git is intentionally absent from the private PATH, so this does not check Git-backed demo snapshots. |
| `ccx ui --no-open --export ...` | Pass using source fallback | Generates a static page from the isolated hub. Live serving, buttons and browser appearance were not checked. |
| README first delegation, then `ccx show` | Pass using source fallback | Exact read-only task is dispatched through the PATH fake; a completed receipt can be inspected. The fake does not actually summarize README or prove answer quality. |

The first two development attempts also exposed missing helper modules in the walkthrough's copied fake fixtures. Those script defects were corrected by including the fakes' existing helper modules. They were not relayline product defects. Failed artifacts remain retained; they were not counted as successful installations.

## Small fixes and regression checks

Setup now names the required project folder containing README.md before showing its first task. It also tells the person to inspect `ccx show <run_id>` and gives both `--ok 1 (correct)` and `--ok 0 (wrong)`. Previously the output omitted the folder assumption and showed only a positive verdict command.

`tests/test_walkthrough.py` checks environment isolation, invokes the actual script as a subprocess from outside the checkout, verifies generated pages and fake delegation, and checks setup's new instructions through its CLI. The script keeps installation failures as Fail even when subsequent source checks pass; zero exit status alone does not hide setup/doctor's printed FAIL sub-checks. Targeted setup regressions also retain existing behavior. Final command: `python -m pytest -q tests/test_walkthrough.py tests/test_firstrun.py -k 'walkthrough or SetupFirstRun' -x` — **7 passed, 34 deselected**, process exit 0. The full suite was not run. No command or option was removed; defaults, existing JSON meanings and exit-code contracts are unchanged.

## Larger items / not run

An installed-wheel/editable run with available build wheels, actual pipx and Claude marketplace plugin installation, real authentication, hook execution/trust, real model results, live UI interaction and Linux/macOS behavior remain **Unknown / not run**. The README's application-specific date-parser example needs an existing project/test file and is illustrative, not a command that can work in an empty directory. None of these were broadened into this task.

The script returns nonzero when installation fails, even if source checks pass. Use the step records rather than treating the overall result as a product-quality score. The report does not establish faster, cheaper or more accurate behavior.
