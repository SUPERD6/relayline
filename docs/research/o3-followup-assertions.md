# O3 follow-up assertion changes

[中文](o3-followup-assertions.zh.md)

The lead explicitly authorized updating the new dispatch/relay tests for review items 4 and 5.
The following are the changed pre-existing assertions; other existing assertions remain.

| Test in tests/test_dispatch.py | Previous expectation | New expectation |
|---|---|---|
| Unknown case in escalation policy parameterization | `False` | `True` |
| Unknown baseline integration | `len(attempts) == 1` | attempt tiers `['T1', 'T2']`; `check_failed` and comparison `Unknown` remain |
| Passing opaque command | tiers `['T1']` | tiers `['T2']` |
| Passing opaque command receipt | `dispatch.escalated == 0` | `dispatch` absent; baseline record remains absent |
| Failing opaque command followed by success | tiers `['T1', 'T2']` | tiers `['T2', 'T3']` |
| Failing opaque command receipt | `dispatch.escalated == 1` | `dispatch` absent; final check still passes |

| Test in tests/test_relay.py | Previous expectation | New expectation |
|---|---|---|
| Exact installed bare StopFailure hook command | only `quota_signal.source == 'StopFailure'` | full signal `{'kind': 'rate_limit_unconfirmed', 'source': 'StopFailure'}`; source stays unchanged |

Additional assertions now verify unconfirmed packet/notice state, wait-or-manual advice without stop advice,
no subprocess before force, successful explicit forced launch, confirmed quota launch without force,
and force requirements on legacy unmarked StopFailure/rate_limit_event packets.

The shared dispatch fixture previously emitted simulated pytest output from `check_run.py`.
It now runs a real, committed pytest acceptance file. The Unknown-baseline case uses a pre-existing dirty
file so baseline capture is genuinely unavailable. The passing/failing opaque-script cases keep their scripts
and now check the ordinary route. Separate coverage retains passing cheap-pytest acceptance and CLI-error retry.
