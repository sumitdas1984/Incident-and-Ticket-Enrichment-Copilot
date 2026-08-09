"""Ingestion-pipeline errors.

A single :class:`IngestionError` is raised for every failure
mode in the loader / chunker / embedder / index stages. The
type stays simple because there's no caller that wants to
differentiate between failure modes — the CLI entry point
in :mod:`__main__` catches it and exits non-zero.
"""
from __future__ import annotations


class IngestionError(RuntimeError):
    """Raised when the ingestion pipeline cannot produce an index.

    Wraps file-system errors, malformed front-matter, missing
    required fields, and any other failure that should fail
    the indexing step rather than silently skip a document.
    """
