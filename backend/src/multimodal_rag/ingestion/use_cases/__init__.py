"""Use cases of document ingestion, grouped by the flow they serve.

``intake`` accepts uploads and reports job progress for the API, and ``processing``
runs claimed jobs for the worker. Each use case receives its ports through its
constructor and never builds an adapter.
"""
