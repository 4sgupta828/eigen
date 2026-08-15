"""Tech connectors — source-specific selectors/API mapping + normalization ONLY.

Each implements the kernel `Connector` protocol (discover_entities → list_documents →
fetch_artifact). Domain nouns live only in returned refs' facets/extra. All are
fixture-injectable so they run offline in tests; live use fetches over HttpStrategy.
"""
from .arxiv import ArxivConnector
from .edgar import EdgarConnector

__all__ = ["ArxivConnector", "EdgarConnector"]
