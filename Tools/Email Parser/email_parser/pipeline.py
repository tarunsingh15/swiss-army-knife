"""Iterative parse pipeline over a blob worklist."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from email_parser.config import Settings, load_settings
from email_parser.file_parsers.base import Blob, ParseContext, ParseResult
from email_parser.file_parsers.registry import (
    resolve_parser,
    sniff_mime,
    unsupported_document,
)
from email_parser.ids import content_hash, make_doc_id
from email_parser.models import Document, ParseStatus, Provenance

ProgressFn = Callable[[dict], None]


def _depth_cap_document(blob: Blob, ctx: ParseContext, max_depth: int) -> Document:
    """Build a failed document when nesting exceeds the configured depth cap."""
    stub = unsupported_document(blob, ctx, sniff_mime(blob.raw, blob.mime_type))
    return stub.model_copy(
        update={
            "provenance": Provenance(
                parser="pipeline",
                parser_version="0.1.0",
                parsed_at=None,
                status=ParseStatus.failed,
                warnings=[f"depth cap exceeded (max_depth={max_depth})"],
            ),
        }
    )


def _failed_document(blob: Blob, ctx: ParseContext, exc: Exception, parser_name: str) -> Document:
    """Build a failed document when parsing raises an exception."""
    doc_id = make_doc_id(blob.raw)
    sniffed_type = sniff_mime(blob.raw, blob.mime_type)
    base = unsupported_document(blob, ctx, sniffed_type)
    return Document(
        doc_id=doc_id,
        source_type=base.source_type,
        mime_type=sniffed_type,
        root_id=ctx.root_id or doc_id,
        parent_id=ctx.parent_id,
        relation_to_parent=blob.relation_to_parent,
        depth=ctx.depth,
        ordinal=blob.ordinal,
        metadata=base.metadata,
        blocks=[],
        provenance=Provenance(
            parser=parser_name,
            parser_version="0.0.0",
            parsed_at=None,
            status=ParseStatus.failed,
            warnings=[str(exc)],
        ),
    )


def _stamp_document(
    document: Document,
    *,
    root_id: str,
    parent_id: str | None,
    depth: int,
    ordinal: int,
    path: str,
) -> Document:
    """Apply pipeline lineage fields to a parsed document."""
    return document.model_copy(
        update={
            "root_id": root_id,
            "parent_id": parent_id,
            "depth": depth,
            "ordinal": ordinal,
            "path": path,
        }
    )


def process(
    root_blob: Blob,
    settings: Settings | None = None,
    on_progress: ProgressFn | None = None,
) -> list[Document]:
    """Parse root and descendants. Return all documents including failed/unsupported."""
    settings = settings or load_settings()
    queue: deque[tuple[Blob, str | None, str | None, int, int, str]] = deque()
    queue.append((root_blob, None, None, 0, root_blob.ordinal, ""))
    seen: set[str] = set()
    docs: list[Document] = []

    while queue:
        blob, parent_id, root_id, depth, ordinal, path = queue.popleft()

        if depth > settings.max_depth:
            ctx = ParseContext(
                max_depth=settings.max_depth,
                max_fanout=settings.max_fanout,
                depth=depth,
                parent_id=parent_id,
                root_id=root_id,
                pdf_engine=settings.pdf_engine,
            )
            document = _depth_cap_document(blob, ctx, settings.max_depth)
            document = _stamp_document(
                document,
                root_id=root_id or document.doc_id,
                parent_id=parent_id,
                depth=depth,
                ordinal=ordinal,
                path=path,
            )
            if on_progress:
                on_progress(
                    {
                        "doc_id": document.doc_id,
                        "filename": blob.filename,
                        "status": document.provenance.status.value,
                        "depth": depth,
                    }
                )
            docs.append(document)
            continue

        digest = content_hash(blob.raw)
        if digest in seen:
            continue
        seen.add(digest)

        sniffed_type = sniff_mime(blob.raw, blob.mime_type)
        ctx = ParseContext(
            max_depth=settings.max_depth,
            max_fanout=settings.max_fanout,
            depth=depth,
            parent_id=parent_id,
            root_id=root_id,
            pdf_engine=settings.pdf_engine,
        )

        parser = resolve_parser(blob.raw, blob.mime_type, pdf_engine=settings.pdf_engine)
        if parser is None:
            document = unsupported_document(blob, ctx, sniffed_type)
            document = _stamp_document(
                document,
                root_id=root_id or document.doc_id,
                parent_id=parent_id,
                depth=depth,
                ordinal=ordinal,
                path=path,
            )
            if on_progress:
                on_progress(
                    {
                        "doc_id": document.doc_id,
                        "filename": blob.filename,
                        "status": document.provenance.status.value,
                        "depth": depth,
                    }
                )
            docs.append(document)
            continue

        try:
            result: ParseResult = parser.parse(blob, ctx)
            document = result.document
        except Exception as exc:
            document = _failed_document(blob, ctx, exc, parser.name)
            result = ParseResult(document=document, child_blobs=[])

        effective_root_id = root_id or document.doc_id
        document = _stamp_document(
            document,
            root_id=effective_root_id,
            parent_id=parent_id,
            depth=depth,
            ordinal=ordinal,
            path=path,
        )

        child_blobs = result.child_blobs
        if len(child_blobs) > settings.max_fanout:
            extra = len(child_blobs) - settings.max_fanout
            warnings = list(document.provenance.warnings)
            warnings.append(
                f"child fanout truncated: {extra} children dropped (max_fanout={settings.max_fanout})"
            )
            document = document.model_copy(
                update={
                    "provenance": document.provenance.model_copy(update={"warnings": warnings}),
                }
            )
            child_blobs = child_blobs[: settings.max_fanout]

        if on_progress:
            on_progress(
                {
                    "doc_id": document.doc_id,
                    "filename": blob.filename,
                    "status": document.provenance.status.value,
                    "depth": depth,
                }
            )
        docs.append(document)

        for index, child in enumerate(child_blobs):
            relation = child.relation_to_parent or "child"
            child_ordinal = child.ordinal if child.ordinal else index
            child_path = (
                f"{path}/{relation}[{child_ordinal}]"
                if path
                else f"{relation}[{child_ordinal}]"
            )
            queue.append(
                (
                    child,
                    document.doc_id,
                    effective_root_id,
                    depth + 1,
                    child_ordinal,
                    child_path,
                )
            )

    return docs
