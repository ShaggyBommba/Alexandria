# Test Scaffold

This folder keeps the test structure for a new repository. Product-specific
tests have been removed; add new behavior contracts as the domain and
application boundaries emerge.

The canonical testing guide is `docs/tests.md`. Read it before adding,
unskipping, or reshaping tests.

Suggested workflow:

1. Pick the smallest behavior worth preserving.
2. Add the test under the matching architecture folder.
3. Use Arrange, Act, Assert with deterministic fixtures or fakes.
4. Implement the smallest production change that makes the test pass.
5. Run:

```bash
uv run pytest
python3 -m compileall src
python3 -m compileall tests
```

The layout mirrors the project architecture:

- `tests/domain`
- `tests/application`
- `tests/infrastructure`
- `tests/entrypoints`
- `tests/integration`

`tests/test_scaffold.py` is intentionally tiny. It keeps pytest collection
healthy until the first product-specific tests are added.
