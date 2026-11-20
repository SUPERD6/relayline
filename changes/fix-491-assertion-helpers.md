- Evaluation (#491): the assertion count of `scripts/eval/round2_tasks.py` (`assertions`, used by the brief
  check and the trace table) now also counts `eq_()`/`ne_()`/`ok_()` style helpers, `expect_warnings()`,
  `expect_deprecated()`, `expect_raises*()`, `pytest.deprecated_call()` and the other `with` context managers of
  that kind (`raises`, `warns` were already counted). The bare helpers `in_()`/`is_()`/`is_not()` count only as
  plain function calls, because `column.in_(...)` is a SQLAlchemy operator, not a check. Ordinary `assert`
  statements and every name starting with `assert` (`self.assert*`, `assert_*`, `x.assert_()`) count as before;
  the new rule only adds, so counts can rise and never fall, and ids of existing checks can shift for files
  that use the new forms. Frozen task sets keep their hand-completed trace tables.
