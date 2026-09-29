"""Domain core and use case for answering questions from the ingested documents.

This package must not import frameworks, SDKs or providers. It reads what ingestion
produced through the ingestion domain and ports, and reaches the answer model, the
admission control and language identification only through the ports it defines.
"""
