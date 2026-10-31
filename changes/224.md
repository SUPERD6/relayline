- Read tasks get an answer, not a note about one: the sub-agent's usual Finish text now starts with one sentence for
  tasks that ask only for an answer (summarise, explain, find, list): read the files the task names first, put the
  answer itself in `summary`, write nothing to a file; the result schema's `summary` description says the same.
  README's first example on T1 (gpt-6-luna/low, fresh install) ran no command 4/4 + 2/2 times before and read
  README.md 3/3 times after, with a correct three-line answer (~$0.003 a run).
