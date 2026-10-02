"""Multimodal RAG system for technical PDF manuals.

The package is organized by concern: ``ingestion`` and ``answering`` hold the domain
core and its use cases, ``adapters`` holds the integrations with frameworks and external
services, ``bootstrap`` wires them together, and ``shared`` holds cross-cutting concerns
such as configuration, errors and logging.
"""

from importlib.metadata import version

__version__ = version("multimodal-rag")
