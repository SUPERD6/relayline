- A sub-agent CLI's stdout and stderr, and Codex's `-o` last message, are read as bytes and decoded as UTF-8; a line
  that is not UTF-8 falls back to the machine's code page (cp936/GBK on a Chinese Windows), and bytes neither can
  decode stay visible as `\xNN` instead of becoming U+FFFD. A lone `\r` inside a line no longer splits it. Defensive:
  the garbled Chinese in #335 came from reading correct UTF-8 files with Python printing to a pipe in cp936; the FAQ
  now says to use `ccx show` or `PYTHONUTF8=1` (#335).
