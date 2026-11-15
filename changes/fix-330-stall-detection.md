- Experimental stall detection, off by default (#330): `run.stall_minutes` (0 = off) stops an attempt whose sub-CLI
  printed no stdout event for that many minutes, ending its process tree like a timeout. It is recorded as kind
  `timeout` with `"stalled": true`, so every timeout rule (no climb, resumable, not learned) applies unchanged.
  See docs/timeouts.md.
