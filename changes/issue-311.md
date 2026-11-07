- Fix numeric quota/auth hints matching inside UUIDs, hashes, filenames and longer numbers (#311).
  Share boundary-aware matching across failure classification, quota-stop evidence and Claude/Codex auth flags;
  keep standalone HTTP codes, text-hint substring matching, hint priority and existing commands/options.
  Standalone 429/401 values (e.g. line numbers, ports or punctuation-separated timestamp components) can still
  cause false positives; this fix only excludes matches inside ASCII identifiers and longer numbers.
