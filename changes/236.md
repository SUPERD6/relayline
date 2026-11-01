- `ccx demo`: the month of ledger-only runs (the overview's spend) shares one label, so the token page groups them
  as one task. Built in the first hours of a month they were the newest 36 runs and pushed the demo's receipts
  (`demo-r-ok`, ...) off the page's list of 40 tasks; `tests/test_demo.py` failed on the 1st. A test now builds the
  demo at 00:30 on the 1st.
