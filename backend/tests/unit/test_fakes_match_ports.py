"""mypy checks these assignments, so a fake that drifts from its port fails CI."""

from multimodal_rag.ingestion import ports
from tests.fakes import (
    FakeEmbedder,
    FakeExtractor,
    FakeFigureDescriber,
    FakePdfInspector,
    FrozenClock,
    InMemoryBlobStorage,
    InMemoryDocumentRepository,
    InMemoryElementRepository,
    InMemoryJobQueue,
    InMemoryVectorIndex,
    WordTokenCounter,
)


def test_every_fake_satisfies_its_port() -> None:
    clock = FrozenClock()
    queue = InMemoryJobQueue(clock)

    implementations: list[object] = []
    clock_port: ports.Clock = clock
    documents: ports.DocumentRepository = InMemoryDocumentRepository()
    jobs: ports.JobQueue = queue
    elements: ports.ElementRepository = InMemoryElementRepository(queue)
    blobs: ports.BlobStorage = InMemoryBlobStorage()
    inspector: ports.PdfInspector = FakePdfInspector()
    extractor: ports.DocumentExtractor = FakeExtractor()
    describer: ports.FigureDescriber = FakeFigureDescriber()
    embedder: ports.Embedder = FakeEmbedder()
    tokens: ports.TokenCounter = WordTokenCounter()
    index: ports.VectorIndex = InMemoryVectorIndex()
    implementations += [clock_port, documents, jobs, elements, blobs, inspector]
    implementations += [extractor, describer, embedder, tokens, index]

    assert len(implementations) == 11
