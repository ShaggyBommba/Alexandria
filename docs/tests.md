# Tests

This repository uses pytest with a TDD-friendly scaffold. Treat tests as
behavior contracts at architecture boundaries, not as snapshots of private
implementation details.

## Setup

Recommended pytest configuration for a `src/` layout:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
addopts = "-ra"
```

Recommended development dependencies:

```text
pytest
pytest-asyncio
```

The test tree should mirror the runtime architecture when those layers exist:

```text
tests/domain
tests/application
tests/infrastructure
tests/entrypoints
tests/integration
```

Shared setup belongs in:

- `tests/conftest.py` for fixtures and factories
- `tests/fakes.py` for reusable fake ports or adapters

Use module-level skips only for deliberate TDD scaffolds:

```python
pytestmark = pytest.mark.skip(reason="TDD stub: ...")
```

Do not leave real implemented behavior skipped without a clear reason.

## Running Tests

Use:

```bash
uv run pytest
```

For evaluation, always run:

```bash
task test
```

`task test` must execute both validation checks and pytest.

Useful focused commands:

```bash
uv run pytest --collect-only -q
uv run pytest tests/application -q
uv run pytest -k behavior_name -q
```

Always run after code changes:

```bash
python3 -m compileall src
```

For test changes, also run:

```bash
python3 -m compileall tests
uv run pytest --collect-only -q
```

When a test is unskipped or implemented, run the relevant focused pytest command
before broader test groups.

## Activating A Stub

1. Pick the smallest behavior needed for the next improvement.
2. Remove the module-level skip or move one test into an unskipped file.
3. Replace Arrange/Act/Assert comments with executable setup and asserts.
4. Run the test and confirm it fails for the expected reason.
5. Implement the smallest production change.
6. Run the focused test, then the relevant broader test group.
7. Leave unrelated stubs skipped.

Do not activate a whole file unless you are ready to implement the behavior in
that file. A small red test is easier to understand than a wall of expected
failures.

## Unit Test Rules

Write unit tests around observable behavior.

In this template, a unit is usually a class or use-case behavior at a clean
architecture boundary:

- domain model behavior
- application use-case behavior through ports
- infrastructure adapter behavior through public methods
- entrypoint behavior through request, CLI, worker, or process boundaries

Use the Arrange, Act, Assert shape:

```python
def test_runner_marks_job_done(fake_queue, fake_handler, make_job) -> None:
    # Arrange
    job = make_job()

    # Act
    ...

    # Assert
    ...
```

Keep one behavior per test. Multiple asserts are fine when they describe the
same behavior, such as "record was written and job was queued". Split the test
when the asserts describe different behavior.

Prefer deterministic inputs:

- fixed UUIDs when identity matters
- `tmp_path` for filesystem work
- `monkeypatch` for environment variables or global functions
- injected settings instead of ambient `.env` state
- fake ports for application unit tests

Avoid external services in unit tests:

- no real databases unless the test is explicitly an integration test
- no network
- no provider SDK or LLM calls
- no sleeps
- no shared mutable process state unless reset by a fixture

If real infrastructure matters, write an integration test and name it as such.

## Fakes, Mocks, And Ports

Prefer this order:

1. Real implementation, when it is fast, deterministic, and local.
2. Fake implementation, when the real dependency is slow, nondeterministic, or
   external.
3. Mock, when neither a real implementation nor a fake can express the case
   cleanly.

The application layer should be easy to test with fakes because its dependencies
are ports in `src/application/ports.py`.

Use mocks mainly at hard process boundaries:

- web server launch functions
- CLI runner setup
- process spawning
- time and sleep
- environment access
- third-party clients

Do not mock a repository when the repository itself is the subject under test.
Use a real local session or test database in a repository integration test
instead.

When a fake becomes important to many tests, add a small contract test proving
that the fake and real adapter agree on the behavior tests rely on.

## Layer Guidance

Domain tests:

- assert pure model behavior
- do not import application or infrastructure
- use plain values and deterministic ids

Application tests:

- instantiate use cases with port fakes
- assert calls at the boundary only when the call is the behavior
- do not import concrete infrastructure adapters unless testing app wiring

Infrastructure tests:

- test rows, repositories, queues, units of work, config, and clients
- use real local resources only when they stay fast and deterministic
- keep provider SDKs and network clients behind fake clients or local test doubles

Entrypoint tests:

- test request, CLI, worker, and launcher behavior
- patch process and server launch functions
- do not start long-running servers

Integration tests:

- prove collaborations across layers
- keep them fewer than unit tests
- prefer memory/local mode unless the behavior specifically concerns durability

Architecture tests:

- protect dependency direction
- protect provider SDK placement in infrastructure
- protect repository scope
- protect thin app facades

## Manual Smoke Checks

For newly activated app flows, add a small manual validation path only when it
helps inspect behavior end to end. Manual checks are not a replacement for
pytest.

Preferred shape:

1. Arrange deterministic local data.
2. Call the public app boundary.
3. Inspect persistence or observable side effects.
4. Clean up local state.

Use real configured infrastructure for complete smoke checks. Use fakes only in
unit tests or in clearly labeled deterministic scratch checks.

## Naming

Use behavior names:

```text
test_runner_marks_job_done
test_service_rejects_unknown_id
test_outbox_uses_idempotent_key
```

Avoid names that only repeat a method:

```text
test_add
test_run
test_pick
```

Short names are good when they stay clear, but test names should explain the
expected behavior that failed.

## Research Basis

This guide follows the current pytest recommendations for a separate `tests/`
directory with a `src/` layout and configured `pythonpath`, pytest fixtures as
explicit arrange state, `tmp_path` for isolated filesystem tests, and
`monkeypatch` for temporary environment or global patches.

It also follows the broader testing guidance that healthy suites have many fast
unit tests, fewer integration tests, and very few end-to-end tests; and that
tests are more trustworthy when they use real implementations or fakes before
falling back to mocks.

References:

- pytest good integration practices: https://docs.pytest.org/en/stable/explanation/goodpractices.html
- pytest fixtures: https://docs.pytest.org/en/stable/explanation/fixtures.html
- pytest `monkeypatch`: https://docs.pytest.org/en/stable/how-to/monkeypatch.html
- pytest `tmp_path`: https://docs.pytest.org/en/stable/how-to/tmp_path.html
- Python `unittest`: https://docs.python.org/3/library/unittest.html
- Practical Test Pyramid: https://martinfowler.com/articles/practical-test-pyramid.html
- Google Testing Blog on mocks and fakes: https://testing.googleblog.com/2024/02/increase-test-fidelity-by-avoiding-mocks.html
- Software Engineering at Google, test doubles: https://abseil.io/resources/swe-book/html/ch14.html
