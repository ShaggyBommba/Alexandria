# Tests

The test tree mirrors the runtime architecture:

- `tests/domain`
- `tests/application`
- `tests/infrastructure`
- `tests/entrypoints`
- `tests/integration`

The canonical testing guide is `docs/tests.md`. Read it before adding,
unskipping, or reshaping tests.

Run the full local and CI-equivalent matrix with:

```bash
task test
```

Useful focused commands:

```bash
uv run pytest --collect-only -q
uv run pytest tests/application -q
uv run pytest tests/integration/test_end_to_end_flow.py -q
python3 -m compileall src tests
```

Integration tests use deterministic local fakes unless the behavior explicitly
concerns a real infrastructure boundary. `tests/integration/test_end_to_end_flow.py`
is the full local lifecycle smoke: seed, ingest, retrieve before split, process
split-check work, and retrieve again.
