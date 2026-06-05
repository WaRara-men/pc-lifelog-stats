# Security

This app reads ActivityWatch data from the local API only.

Do not commit:

- `.env` files
- ActivityWatch databases or exports
- CSV/JSONL/log files containing personal activity data
- API keys, tokens, certificates, or private keys

The included `.gitignore` excludes common local data and secret file patterns, but review changes before every push.
