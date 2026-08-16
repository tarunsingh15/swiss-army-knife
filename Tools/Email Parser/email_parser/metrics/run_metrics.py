"""Tier A run metrics computed from parsed documents without ground truth."""

from __future__ import annotations

from collections import Counter

from email_parser.models import Document, ParseStatus, SourceType


def compute_run_metrics(
    documents: list[Document],
    elapsed_s: float = 0.0,
    rejected: int = 0,
    deduped: int = 0,
) -> dict:
    """Summarize throughput, outcomes, and partial successes for a parse run."""
    failures_by_status: Counter[str] = Counter()
    attachments_by_type: Counter[str] = Counter()
    accepted = 0
    max_depth = 0
    emails_parsed = 0

    failed_statuses = {ParseStatus.failed, ParseStatus.unsupported}
    children_by_parent: dict[str, list[str]] = {}
    for doc in documents:
        if doc.parent_id is not None:
            children_by_parent.setdefault(doc.parent_id, []).append(doc.doc_id)

    for doc in documents:
        max_depth = max(max_depth, doc.depth)
        status = doc.provenance.status
        failures_by_status[status.value] += 1

        if status in {ParseStatus.ok, ParseStatus.warning}:
            accepted += 1

        if doc.source_type == SourceType.email:
            emails_parsed += 1

        if doc.parent_id is not None:
            attachments_by_type[doc.mime_type] += 1

    def _has_failed_descendant(doc_id: str) -> bool:
        """Return True when any descendant document failed or is unsupported."""
        stack = list(children_by_parent.get(doc_id, []))
        while stack:
            child_id = stack.pop()
            child = next(item for item in documents if item.doc_id == child_id)
            if child.provenance.status in failed_statuses:
                return True
            stack.extend(children_by_parent.get(child_id, []))
        return False

    partial_successes = 0
    for doc in documents:
        if doc.source_type != SourceType.email:
            continue
        if doc.provenance.status not in {ParseStatus.ok, ParseStatus.warning}:
            continue
        if _has_failed_descendant(doc.doc_id):
            partial_successes += 1

    return {
        "tier": "A",
        "accepted": accepted,
        "rejected": rejected,
        "deduped": deduped,
        "emails_parsed": emails_parsed,
        "attachments_by_type": dict(sorted(attachments_by_type.items())),
        "docs_produced": len(documents),
        "max_depth": max_depth,
        "elapsed_s": elapsed_s,
        "failures_by_status": dict(sorted(failures_by_status.items())),
        "partial_successes": partial_successes,
    }
