# Contributing to tierlane

Thanks for helping improve tierlane. Small, focused changes are easiest to review.

## Before you start

- Search existing issues before opening a new one.
- Do not include API keys, tokens, private prompts, personal paths, or customer data.
- For security vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

```bash
git clone https://github.com/MRL-mana/tierlane.git
cd tierlane
python -m venv .venv
python -m pip install -e . pytest
python -m pytest -q
```

## Pull requests

1. Keep the change focused on one problem.
2. Add or update tests when behavior changes.
3. Run `python -m pytest -q` before submitting.
4. Explain the user-visible impact and any safety implications.

By contributing, you agree that your contribution will be licensed under the repository's MIT License.
