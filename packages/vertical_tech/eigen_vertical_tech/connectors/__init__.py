"""Tech connectors — source-specific selectors/API mapping + normalization ONLY.

Each implements the kernel `Connector` protocol (discover_entities → list_documents →
fetch_artifact). Domain nouns live only in returned refs' facets/extra. All are
fixture-injectable so they run offline in tests; live use fetches over HttpStrategy.
"""
from .arxiv import ArxivConnector
from .crossref import CrossrefConnector
from .edgar import EdgarConnector
from .gdelt import GdeltConnector
from .github import GithubConnector
from .hackernews import HackerNewsConnector
from .huggingface import HuggingFaceConnector
from .openalex import OpenAlexConnector
from .openreview import OpenReviewConnector
from .patentsview import PatentsViewConnector
from .reddit import RedditConnector
from .semantic_scholar import SemanticScholarConnector
from .stackexchange import StackExchangeConnector
from .wikidata import WikidataConnector

__all__ = ["ArxivConnector", "CrossrefConnector", "EdgarConnector", "GdeltConnector",
           "GithubConnector", "HackerNewsConnector", "HuggingFaceConnector", "OpenAlexConnector",
           "OpenReviewConnector", "PatentsViewConnector", "RedditConnector", "SemanticScholarConnector",
           "StackExchangeConnector", "WikidataConnector"]
