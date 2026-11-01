- A fresh run's first message now opens with ccx's fixed rules; the run id, the lead and the workspace come after
  them (`Run: <id>; lead: <who>`), so every run starts with the same ~700 characters a provider's prefix cache can
  reuse (P0-11 item 4). Small: about $0.001 a run at most. `[ccx sub-task` still starts the message.
