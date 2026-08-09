"""Unit tests for the RAG corpus loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag.ingestion import LoadedDocument, load_documents
from rag.ingestion.errors import IngestionError


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _valid_doc(doc_id: str = "doc-1") -> str:
    return (
        "---\n"
        f"doc_id: {doc_id}\n"
        "title: Doc 1\n"
        "source_type: troubleshooting\n"
        "version: 1.0\n"
        "last_updated: 2026-01-01\n"
        "---\n"
        "\n"
        "# Heading\n"
        "\n"
        "Body text.\n"
    )


def test_loads_a_single_well_formed_document(tmp_path: Path) -> None:
    _write(tmp_path, "doc-1.md", _valid_doc())
    docs = load_documents(tmp_path)
    assert len(docs) == 1
    doc = docs[0]
    assert isinstance(doc, LoadedDocument)
    assert doc.doc_id == "doc-1"
    assert doc.title == "Doc 1"
    assert doc.source_type == "troubleshooting"
    assert doc.version == "1.0"
    assert doc.last_updated == "2026-01-01"
    assert doc.body.startswith("# Heading")
    assert doc.path == (tmp_path / "doc-1.md").resolve()


def test_loads_optional_fields(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "doc-1.md",
        "---\n"
        "doc_id: doc-1\n"
        "title: Doc 1\n"
        "source_type: knowledge_article\n"
        "asset_class: boiler\n"
        "severity: critical\n"
        "tags: [boiler, leak]\n"
        "version: 1.0\n"
        "last_updated: 2026-01-01\n"
        "---\n"
        "Body.\n",
    )
    [doc] = load_documents(tmp_path)
    assert doc.asset_class == "boiler"
    assert doc.severity == "critical"
    assert doc.tags == ["boiler", "leak"]


def test_rejects_missing_required_field(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "doc-1.md",
        "---\n"
        "doc_id: doc-1\n"
        "title: Doc 1\n"
        "source_type: troubleshooting\n"
        "version: 1.0\n"
        # last_updated missing
        "---\n"
        "Body.\n",
    )
    with pytest.raises(IngestionError, match="missing required fields"):
        load_documents(tmp_path)


def test_rejects_unknown_field(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "doc-1.md",
        "---\n"
        "doc_id: doc-1\n"
        "title: Doc 1\n"
        "source_type: troubleshooting\n"
        "version: 1.0\n"
        "last_updated: 2026-01-01\n"
        "bogus_field: 1\n"
        "---\n"
        "Body.\n",
    )
    with pytest.raises(IngestionError, match="unknown fields"):
        load_documents(tmp_path)


def test_rejects_missing_front_matter(tmp_path: Path) -> None:
    _write(tmp_path, "doc-1.md", "# Just a heading\nNo front-matter here.\n")
    with pytest.raises(IngestionError, match="missing or malformed front-matter"):
        load_documents(tmp_path)


def test_rejects_invalid_yaml(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "doc-1.md",
        "---\n"
        "doc_id: doc-1\n"
        "title: [: unclosed\n"
        "source_type: troubleshooting\n"
        "version: 1.0\n"
        "last_updated: 2026-01-01\n"
        "---\n"
        "Body.\n",
    )
    with pytest.raises(IngestionError, match="invalid YAML"):
        load_documents(tmp_path)


def test_rejects_duplicate_doc_id(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", _valid_doc("doc-1"))
    _write(tmp_path, "b.md", _valid_doc("doc-1"))
    with pytest.raises(IngestionError, match="Duplicate doc_id"):
        load_documents(tmp_path)


def test_rejects_unknown_source_type(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "doc-1.md",
        "---\n"
        "doc_id: doc-1\n"
        "title: Doc 1\n"
        "source_type: marketing\n"
        "version: 1.0\n"
        "last_updated: 2026-01-01\n"
        "---\n"
        "Body.\n",
    )
    with pytest.raises(IngestionError, match="source_type 'marketing' not in"):
        load_documents(tmp_path)


def test_rejects_bad_doc_id_shape(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "doc-1.md",
        "---\n"
        "doc_id: 'Bad ID with spaces'\n"
        "title: Doc 1\n"
        "source_type: troubleshooting\n"
        "version: 1.0\n"
        "last_updated: 2026-01-01\n"
        "---\n"
        "Body.\n",
    )
    with pytest.raises(IngestionError, match="does not match"):
        load_documents(tmp_path)


def test_rejects_missing_corpus_directory(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="does not exist"):
        load_documents(tmp_path / "nope")


def test_rejects_path_that_is_a_file(tmp_path: Path) -> None:
    p = tmp_path / "a.md"
    p.write_text(_valid_doc(), encoding="utf-8")
    with pytest.raises(IngestionError, match="not a directory"):
        load_documents(p)


def test_walks_subdirectories(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    _write(tmp_path, "a.md", _valid_doc("doc-1"))
    _write(tmp_path / "sub", "b.md", _valid_doc("doc-2"))
    docs = load_documents(tmp_path)
    assert [d.doc_id for d in docs] == ["doc-1", "doc-2"]


def test_returns_documents_sorted_by_id(tmp_path: Path) -> None:
    _write(tmp_path, "z.md", _valid_doc("doc-z"))
    _write(tmp_path, "a.md", _valid_doc("doc-a"))
    docs = load_documents(tmp_path)
    assert [d.doc_id for d in docs] == ["doc-a", "doc-z"]


def test_empty_corpus_returns_empty_list(tmp_path: Path) -> None:
    assert load_documents(tmp_path) == []


def test_tags_default_to_empty_list_when_missing(tmp_path: Path) -> None:
    _write(tmp_path, "doc-1.md", _valid_doc())
    [doc] = load_documents(tmp_path)
    assert doc.tags == []
