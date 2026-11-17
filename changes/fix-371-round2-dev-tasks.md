- Evaluation (#371): `scripts/eval/round2_tasks.py select` no longer stops once B has 60 and C has 24 tasks; it
  walks on in the same order and picks the round-2 development tasks the pre-registration asks for: the next 4
  B-size commits for B, then the next 2 C-size commits for C, under the same hidden-test rule and the same
  repository caps (a group's development tasks count toward that group's cap). They go into a separate `dev`
  field (`{"B": [...], "C": [...]}`, each task marked `"dev": true`) with `dev_shortfall`, so the selection JSON
  and its manifest freeze them with the final tasks; the final B and C lists are unchanged. The command prints the
  development counts and, when commits run out, how many development tasks to author; that shortfall does not
  change the exit code. `env-check` and `leak` now cover the development tasks too.
