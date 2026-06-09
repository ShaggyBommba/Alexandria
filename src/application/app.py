from functools import lru_cache
from uuid import UUID

from domain.entity import Node
from application.ports import DocHit, DocIn, NodeHit
from application.usecases.ingest import Ingest
from application.usecases.lint import Lint
from application.usecases.refs import Refs
from application.usecases.rerank import Rerank
from application.usecases.retrieve import Retrieve
from application.usecases.route import Route
from application.usecases.seed import Seed
from application.usecases.split import Split
from infrastructure.config import Settings, get_settings
from infrastructure.embeddings import make_embedder
from infrastructure.persistence.db import Db
from infrastructure.observability.logger import LoggingService
from infrastructure.repositories.nodes import NodeRepo
from infrastructure.repositories.outbox import OutboxRepo
from logging import getLogger

logging = getLogger(__name__)

class App:
    """Application boundary for alexandria workflows."""

    def __init__(self, settings: Settings) -> None:
        """Keep app settings and injected use cases."""
        self.settings = settings
        self.db = Db(settings.database)
        self.session = self.db.session()
        self.nodes = NodeRepo(self.session)
        self.outbox = OutboxRepo(self.session, settings.queue)
        self.queue = self.outbox
        self.embedder = make_embedder(settings.embedding.provider, settings.embedding)
        self.search = None

        # Each case is wired as a workflow boundary. Concrete repository,
        # search, LLM, and ranking adapters can be injected here as they land.
        self.seed_case = Seed()
        self.route_case = Route(self.nodes)
        self.rerank_case = Rerank()
        self.refs_case = Refs()
        self.split_case = Split()
        self.lint_case = Lint(split=self.split_case)
        self.ingest_case = Ingest(
            embedder=self.embedder,
            seed=self.seed_case,
            route=self.route_case,
        )
        self.retrieve_case = Retrieve(
            search=self.search,
            embedder=self.embedder,
            route=self.route_case,
            refs=None,
            rerank=self.rerank_case,
        )

        self.setup()

    def setup(self) -> None:
        """Create database schema for app initialization."""
        self.db.create_all()

    async def seed(self) -> Node:
        """Ensure the index has a root node."""
        # Ensure ingest and retrieval have a root node to start from.
        return await self.seed_case.run()

    async def route(self, embedding: list[float], limit: int = 10) -> list[NodeHit]:
        """Find candidate leaf nodes for an embedding."""
        # Walk from the root through child nodes by embedding distance.
        # Keep a beam of candidate paths so ingest and retrieval can choose from
        # several plausible leaves instead of committing to one early branch.
        return await self.route_case.run(embedding, limit=limit)

    async def ingest(self, doc: DocIn) -> UUID:
        """Link a document to the best matching entity."""
        # Ensure the root exists before routing starts.
        # Embed and summarize the document through swappable application ports.
        # Route the document to candidate leaves and attach it to the chosen leaf.
        # Queue a split-check job when the chosen leaf becomes full.
        return await self.ingest_case.run(doc)
    
    async def lint(self, node_id: UUID) -> None:
        """Run split evaluation for a linked entity."""
        # Reload the queued node after the worker claims the split-check job.
        # Confirm the node is still active, still a leaf, and still over capacity.
        # Delegate to split only when the current database state still requires it.
        return await self.lint_case.run(node_id)

    async def split(self, node_id: UUID) -> None:
        """Split a full leaf node."""
        # Load the node and documents that belong to the full leaf.
        # Ask the splitter adapter for child nodes and document assignments.
        # Validate the adapter output against local ids before writing changes.
        # Commit child creation, document moves, stale-ref cleanup, and follow-up work together.
        return await self.split_case.run(node_id)

    async def refs(self, node_id: UUID, limit: int = 10) -> None:
        """Build semantic references for one entity."""
        # Drop stale outgoing references for the node.
        # Compare the node against other active leaves by embedding distance.
        # Store the top directed references for retrieval expansion.
        return await self.refs_case.run(node_id, limit=limit)

    async def retrieve(self, query: str, limit: int = 10) -> list[DocHit]:
        """Return documents relevant to a query."""
        # Embed the query and route it through the tree with beam search.
        # Expand routed leaves through directed references to widen the scope.
        # Run hybrid search over scoped documents using embeddings plus BM25.
        # Rerank the hybrid candidates and return the final top results.
        return await self.retrieve_case.run(query, limit=limit)

    async def rerank(self, query: str, hits: list[DocHit], limit: int = 10) -> list[DocHit]:
        """Rerank document hits for one query."""
        # Pass candidate documents to the ranking adapter.
        # Return only the highest-ranked hits requested by the caller.
        return await self.rerank_case.run(query, hits, limit=limit)

    @property
    def version(self):
        return self.settings.app.app_version

    @property
    def health(self):
        return True

    @property
    def name(self):
        return self.settings.app.app_name


@lru_cache(maxsize=1)
def get_app() -> App:
    settings = get_settings()
    LoggingService.setup(settings.logging)
    logging.info(f"Starting {settings.app.app_name} version {settings.app.app_version}")
    app = App(settings)
    return app
