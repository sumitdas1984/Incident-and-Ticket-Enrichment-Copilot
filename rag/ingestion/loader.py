"""Markdown + front-matter loader for the RAG corpus.

Walks a directory of ``*.md`` files, splits each into YAML
front-matter and Markdown body, and yields a :class:`LoadedDocument`
for each. The loader is the only ingestion stage that touches
the file system; downstream stages (chunking, embedding,
indexing) consume :class:`LoadedDocument` objects in memory.

Why hand-rolled front-matter
----------------------------

Front-matter is a well-defined grammar: a ``---\\n`` opener, a
YAML block, a ``\\n---\\n`` closer, then the body. ``python-frontmatter``
reads this fine but adds a runtime dep and a metadata layer we
don't need. The 30-line parser below covers the cases we expect
to see in this corpus and surfaces malformed input as a loud
:class:`IngestionError` rather than silently dropping the field.

Why a frozen dataclass
----------------------

``LoadedDocument`` is the unit that flows through chunking,
embedding, and indexing. Freezing it makes accidental mutation
between stages a hard error and makes the loader output safe to
share across threads if ingestion is parallelised later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .errors import IngestionError

# Required front-matter fields. The corpus test fixture
# (test_corpus.py) enforces these on every committed doc.
REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"doc_id", "title", "source_type", "version", "last_updated"}
)
OPTIONAL_FIELDS: frozenset[str] = frozenset(
    {"asset_class", "severity", "tags"}
)

# Allowed source types. The corpus test enforces coverage of
# at least four of these; the loader enforces that every
# committed doc is one of them.
ALLOWED_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "troubleshooting",
        "procedure",
        "knowledge_article",
        "resolution_note",
        "escalation",
    }
)

# Front-matter grammar: ``---\n`` (with optional BOM/whitespace),
# YAML block, ``\n---`` (or end-of-document), then body.
_FRONTMATTER_RE = re.compile(
    r"\A\s*---\s*\n(?P<yaml>.*?)\n---\s*(?:\n|\Z)",
    re.DOTALL,
)

# Filename stem allowed characters. Used to detect accidental
# path injection in the doc_id.
_DOC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,80}$")


@dataclass(frozen=True)
class LoadedDocument:
    """A Markdown doc with its front-matter parsed.

    Attributes
    ----------
    doc_id:
        Stable identifier; doubles as the filename stem.
    title:
        Human-readable title.
    source_type:
        Coarse category (``troubleshooting`` / ``procedure`` /
        ``knowledge_article`` / ``resolution_note`` /
        ``escalation``).
    asset_class:
        Optional. The asset class the doc applies to (e.g.
        ``boiler``). ``None`` for site-wide docs.
    severity:
        Optional. The severity band (e.g. ``critical``).
    tags:
        List of free-form tags. Always a list (never ``None``)
        so downstream chunking can iterate without a None check.
    body:
        The Markdown body, with front-matter stripped.
    path:
        Absolute path to the source file.
    version:
        Doc version string. Format is not enforced; the loader
        passes through whatever is in the front-matter.
    last_updated:
        Doc last-updated date as a string. Format is not
        enforced here; the corpus test asserts it is a
        non-empty ISO-shaped string.
    """

    doc_id: str
    title: str
    source_type: str
    asset_class: str | None
    severity: str | None
    tags: list[str] = field(default_factory=list)
    body: str = ""
    path: Path = Path(".")
    version: str = "0.0.0"
    last_updated: str = ""

    def __post_init__(self) -> None:
        # Validate identifier shape. We freeze the object in
        # ``__init__``; ``object.__setattr__`` bypasses the
        # frozen check, so we use it only to coerce types
        # without rewriting the field.
        if not _DOC_ID_RE.match(self.doc_id):
            raise IngestionError(
                f"doc_id {self.doc_id!r} does not match "
                f"{_DOC_ID_RE.pattern!r}"
            )
        if self.source_type not in ALLOWED_SOURCE_TYPES:
            raise IngestionError(
                f"doc_id {self.doc_id!r}: source_type "
                f"{self.source_type!r} not in "
                f"{sorted(ALLOWED_SOURCE_TYPES)}"
            )


def load_documents(corpus_dir: Path) -> list[LoadedDocument]:
    """Load every ``*.md`` under ``corpus_dir`` into :class:`LoadedDocument`.

    Walks recursively. Files without a front-matter block are
    rejected. Duplicate ``doc_id`` values across the corpus are
    rejected (catches copy-paste mistakes during authoring).

    Raises
    ------
    IngestionError
        If the corpus directory does not exist, contains a
        markdown file with malformed or missing front-matter,
        or contains two docs with the same ``doc_id``.
    """
    if not corpus_dir.exists():
        raise IngestionError(f"Corpus directory does not exist: {corpus_dir}")
    if not corpus_dir.is_dir():
        raise IngestionError(f"Corpus path is not a directory: {corpus_dir}")

    docs: list[LoadedDocument] = []
    seen_ids: dict[str, Path] = {}

    for path in sorted(corpus_dir.rglob("*.md")):
        doc = _load_one(path)
        if doc.doc_id in seen_ids:
            raise IngestionError(
                f"Duplicate doc_id {doc.doc_id!r} in "
                f"{seen_ids[doc.doc_id]} and {doc.path}"
            )
        seen_ids[doc.doc_id] = doc.path
        docs.append(doc)

    # Sort by doc_id for deterministic ingestion order.
    # The pipeline is otherwise order-independent, but a
    # deterministic order means the persisted index is
    # byte-identical across rebuilds with the same corpus
    # (verified by the determinism test).
    docs.sort(key=lambda d: d.doc_id)
    return docs


def _load_one(path: Path) -> LoadedDocument:
    """Parse a single markdown file into a :class:`LoadedDocument`."""
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise IngestionError(
            f"{path}: missing or malformed front-matter "
            f"(expected `---\\n...\\n---\\n` at the top of the file)"
        )
    raw_yaml = match.group("yaml")
    body = text[match.end():]

    try:
        meta = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise IngestionError(f"{path}: invalid YAML in front-matter: {exc}") from exc

    if not isinstance(meta, dict):
        raise IngestionError(
            f"{path}: front-matter must be a YAML mapping, got {type(meta).__name__}"
        )

    missing = REQUIRED_FIELDS - meta.keys()
    if missing:
        raise IngestionError(
            f"{path}: front-matter missing required fields: {sorted(missing)}"
        )

    unknown = set(meta.keys()) - REQUIRED_FIELDS - OPTIONAL_FIELDS
    if unknown:
        raise IngestionError(
            f"{path}: front-matter has unknown fields: {sorted(unknown)}"
        )

    tags = meta.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise IngestionError(f"{path}: front-matter `tags` must be a list of strings")

    asset_class = meta.get("asset_class")
    severity = meta.get("severity")

    return LoadedDocument(
        doc_id=str(meta["doc_id"]),
        title=str(meta["title"]),
        source_type=str(meta["source_type"]),
        asset_class=str(asset_class) if asset_class is not None else None,
        severity=str(severity) if severity is not None else None,
        tags=list(tags),
        version=str(meta["version"]),
        last_updated=str(meta["last_updated"]),
        body=body,
        path=path.resolve(),
    )
