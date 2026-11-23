# agent-md-audit

Offline CLI that audits AI agent instruction files (AGENTS.md and friends). Python 3.10+, no runtime dependencies.

## Layout

- `src/agent_md_audit/doc.py` loads a file and knows about the project around it.
- `src/agent_md_audit/rules.py` holds every rule; add new ones to `RULES`.
- `src/agent_md_audit/cli.py` handles arguments and output formats.
- `examples/messy/AGENTS.md` should trip every rule except AM101 and AM107.

## Commands

```bash
pip install -e ".[dev]"
pytest -q
python -m agent_md_audit examples
```

## Conventions

- Errors (AM0xx) are facts that can be checked; warnings (AM1xx) are judgment calls.
- Every rule needs a test that fires and a test that stays quiet.
- Keep the false-positive rate low: when unsure, do not report.
