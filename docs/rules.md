# Coding Rules

These rules capture reusable coding standards. They are intentionally practical:
use them to guide new code, refactors, stubs, and reviews without baking in
product-specific behavior.

## Document Ownership

Keep this file limited to reusable coding standards.

Never put repository-specific architecture, table shapes, current implementation
status, provider choices, or task workflow procedure in this file.

Use the documentation set this way:

- `AGENTS.md` defines bootstrap loading order, document precedence, required
  context, and the default agent role.
- `docs/rules.md` defines reusable coding standards.
- `docs/workflows.md` defines task execution, planning, review, validation,
  worktree safety, subagent use, and documentation-update procedure.
- `docs/architecture.md` defines repository-specific architecture, models,
  ports, APIs, flows, and current implementation state.
- `docs/tests.md` defines test standards and test workflows.

If a proposed rule needs repository names, concrete table shapes, current method
names, or implementation status, put it in `docs/architecture.md` instead.

## Golden Rules

Prefer typed contracts at uncertain boundaries. When data crosses from an API
request, queue payload, config source, LLM/tool response, file, database row, or
other untrusted adapter, describe the expected shape with a Pydantic model,
domain value object, dataclass, or protocol return type. Let the framework
validate and parse whenever it can. Avoid open-ended `dict`, `Mapping`,
stringly-typed JSON, or manual response-shape branching when a typed schema is
available.

Keep orchestration thin. A use case, adapter method, or factory should read as a
small sequence of responsibilities: prepare input, call the dependency, validate
or clean the result, and return the boundary value. If one method is also
loading config, constructing clients, traversing storage, parsing output,
filtering results, and making business decisions, split those responsibilities
at the architecture boundary that owns them.

Use the strongest native abstraction before hand-rolling behavior. Prefer
framework validation over ad hoc type checks, ORM relationships over lists of
foreign ids, structured tool or model output over custom JSON parsing, and
repository/query APIs over string manipulation. Hand-written parsing or plumbing
is a fallback, not the default.

Factories compose; adapters execute; use cases decide. Factories should assemble
configured dependencies. Adapters should translate between infrastructure and
application ports. Application services should own workflow decisions. Do not
hide storage access, business rules, client construction, and cleanup inside one
convenience class.

Make external dependencies explicit and lazy. Constructor wiring should not
surprise callers by requiring credentials, network access, running services, or
expensive side effects unless that is the explicit contract. Missing optional
runtime dependencies should stay visible as typed adapter or config errors at
the point where the dependency is actually used or deliberately built.

Clean untrusted output before it reaches application decisions. Tool responses,
queue payloads, API ids, config-derived values, and client responses must be
checked against local truth such as known records, candidate sets, allowed
states, and idempotency keys before they can drive writes or workflow
transitions. Unknown, duplicate, malformed, or out-of-scope values should be
rejected or normalized at the boundary that receives them.

Make decisions observable without changing public contracts. If an adapter or
use case receives useful explanation data, log it at `debug` with the relevant
ids. Do not expand application ports, return shapes, or persistence models just
to expose diagnostics. Avoid stdout callbacks or prints in runtime code; use
configured logging.

## Naming

Prefer short names when they stay clear.

Good class names:

```text
App
Runner
Parser
Loader
Sender
Repo
UserRepo
JobRepo
OutboxRepo
Queue
Db
SqlUnitOfWork
```

Good method names:

```text
add
get
all
rm
find
pick
make
run
send
load
save
claim
append
due
mark
commit
rollback
```

Use one word when the meaning is obvious from the class.

For example:

```python
repo.add(item)
queue.claim(limit)
runner.run(job)
sender.send(message)
```

Do not use private-style function or method names with a leading underscore.
If a helper is worth naming, give it a clear normal name.

Avoid:

```python
def _expire_items(...): ...
```

Prefer:

```python
def expire_items(...): ...
```

Avoid long service names unless the short name would hide meaning.

## Layers

Prefer a small clean-architecture split unless the repository has a simpler
documented structure:

```text
domain
application
infrastructure
entrypoints
```

The dependency direction should stay simple:

```text
entrypoints -> application -> domain
infrastructure -> application ports
```

Domain code should not import application, infrastructure, or entrypoint code.

Application use cases should prefer ports over concrete infrastructure classes.

Infrastructure classes may implement application ports.

Entrypoints translate transport concerns into application calls. They should not
contain business decisions.

## Errors

Use specific typed errors for expected failures.

Each boundary owns its own error module when the layer exists:

```text
src/domain/error.py
src/application/error.py
src/infrastructure/error.py
src/entrypoints/error.py
```

When starting a new use case, define any new expected failure in the correct
boundary before raising it.

Use the boundary that owns the meaning of the failure:

- domain errors for domain invariants
- application errors for use-case decisions and invalid workflow state
- infrastructure errors for adapter, persistence, queue, config, and client failures
- entrypoint errors for request, command, worker, or transport translation failures

Prefer a new specific subclass when the existing error name does not clearly
describe the failure. Avoid raising broad `RuntimeError` or base error classes
for expected behavior.

Keep error direction aligned with the architecture:

```text
application may import domain errors
infrastructure may import domain errors while implementing adapters
entrypoints may import domain or application errors for translation
domain must not import application, infrastructure, or entrypoints
```

Give expected errors a stable `code`. Set `retryable` when workers, queues, or
callers need to distinguish retryable failures from permanent ones.

## Protocols And Ports

When an application service depends on a swappable dependency, type the
dependency as a `Protocol`.

Store shared application protocols in:

```text
src/application/ports.py
```

Examples:

```python
class Store(Protocol): ...
class Queue(Protocol): ...
class Client(Protocol): ...
class UnitOfWork(Protocol): ...
```

Use protocols for dependencies that may later be backed by a database, memory
adapter, external client, durable queue, or test double.

## Application Services

Application services coordinate behavior. They should not know infrastructure
details.

Good service boundaries:

- one use case per class or focused function
- decisions live near the workflow they affect
- calls to repositories, queues, and clients go through ports
- validation of adapter output happens before writes or state transitions
- multi-step writes go through a transaction boundary when atomicity matters

Keep public application boundaries thin. A facade such as `App` may assemble or
expose workflows, but business decisions should live in use cases.

## Repositories

Repositories should be boring.

They store and fetch data. They should not decide:

- whether a workflow should run
- which external action should happen next
- how to interpret provider-specific output
- when to publish jobs or messages unless the repository is specifically for jobs

Use repository names like:

```text
UserRepo
JobRepo
OutboxRepo
```

Use repository method names like:

```text
add
get
all
rm
find
count
append
due
claim
mark
```

## Data Modeling

Use explicit persistence models for stored data.

Use Pydantic, dataclasses, or domain models for typed domain data and API
boundaries.

Do not store lists of ids inside a SQL row when the relationship is relational.
Use join tables or association models for many-to-many relationships.

Keep persistence concerns out of the domain layer unless
`docs/architecture.md` explicitly documents a shared domain/persistence model.
ORM sessions, migrations, vector indexes, and provider-specific fields belong
in infrastructure.

## Queues And Outbox

Use a queue when work can run asynchronously.

Use an outbox when a write and a later async action must be committed together.
The durable write should include an idempotency key whenever duplicate
publication or retry is possible.

Outbox jobs should support clear states such as:

```text
pending
running
done
failed
```

Workers should process jobs through an application boundary, not by reaching
into lower-level use cases or repositories directly.

## External Clients And Agents

Keep provider SDKs, LLM frameworks, API clients, and tool objects in
infrastructure adapters.

Application use cases should depend on small ports that describe the behavior
they need. They should not create provider clients, pass provider-specific tool
objects, or branch on provider-specific response types.

Adapter output must be validated before it drives application decisions. When an
adapter can explain its choice, log the explanation at `debug` rather than
changing the application contract only for diagnostics.

## Config

Inject settings into classes that need them.

Settings usually live in:

```text
src/infrastructure/config.py
```

Environment variables should use a project-specific prefix and nested sections
separated by:

```text
__
```

Prefer grouped config:

```text
app
database
logging
queue
clients
```

Avoid hidden global config reads inside services. Pass settings through
constructors.

## Logging

Logging is required for runtime code.

Each runtime module or script should define a module logger near the imports:

```python
from logging import getLogger

logging = getLogger(__name__)
```

Configure handlers once at the application or entrypoint boundary. Do not
configure handlers inside repositories, use cases, adapters, or domain modules.

Use log levels strategically:

- `debug` for internal decisions, selected ids, counts, branch choices, and
  values useful while tracing behavior
- `info` for lifecycle milestones, startup/shutdown, completed high-level
  workflows, and durable state transitions
- `error` for failures that prevent a workflow from completing, with useful
  identifiers and exception context when catching exceptions

Prefer logs over `print` for diagnostics. Use `print` only for intentional CLI
output or small validation scripts.

## Contracts And Function Shape

Avoid broad contracts by default.

A function should do the job its caller needs, not every nearby job an input
could possibly imply. If a function receives a path and is responsible only for
reading a file, it is often reasonable for the caller or entrypoint boundary to
own checks such as "does this path exist?" or "is this user input valid?".

Prefer narrow contracts with clear assumptions:

```python
def read(path: Path) -> str:
    """Read an existing text file."""
    return path.read_text()
```

Do not add defensive branches for `None`, missing files, URLs, directories,
bytes, strings, retries, or alternate encodings unless the contract or caller
requires those cases.

When an assumption changes the design, ask the user a targeted question. When
local context already answers it, make the narrow assumption and document it in
a short docstring or nearby comment. Keep validation at the boundary that owns
the meaning of invalid input.

Avoid tiny helper sprawl.

Readable code is not always the code with the most functions. It is fine for a
function to stay larger while the behavior is still forming. Break code out only
when the new function creates a meaningful improvement:

- it names a real domain or workflow concept
- it protects a layer, port, adapter, or transaction boundary
- it removes meaningful duplication
- it isolates a complex algorithm or branch
- it gives tests a useful behavior boundary

Do not extract helpers just to make code look idiomatic. Too many functions that
do too little make the flow harder to follow.

## Stubs First

It is okay to write signatures before implementations.

When writing stubs, include:

- clear type signatures
- short docstrings
- explicit dependency injection
- no fake business logic

Use `...` for unimplemented behavior.

Avoid pretending a stub is real. If persistence, external-client, or transaction
behavior is not implemented yet, leave it visibly stubbed.

## Comments And Docstrings

Use concise docstrings for classes and public methods.

Explain what the class or function is responsible for.

Do not add noisy comments that repeat the code.

Good:

```python
class Runner:
    """Runs one queued job through the application boundary."""
```

Avoid:

```python
# Set self.repo to repo
self.repo = repo
```

## Transactions

Use a unit of work when multiple writes must commit together.

Examples:

```text
write primary record
write audit record
commit
```

```text
write domain record
write outbox job
commit
```

Do not let one required write commit without the other when the workflow
requires atomicity.

## Async

Use async at boundaries that may call queues, workers, network clients, LLMs, or
other slow external systems.

Keep synchronous repository methods only where the storage implementation is
synchronous and callers do not need concurrency.

Do not make code async only for style. Let the dependency behavior decide.

## Style

Keep code small and explicit.

Prefer constructor injection over module-level singletons.

Prefer simple classes over clever abstractions.

Add an abstraction only when it protects a real boundary:

```text
port
repository
adapter
unit of work
queue
```

Do not add extra layers just because they sound architectural.
