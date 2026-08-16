"""Tier C accuracy metrics for labeled evaluation corpora."""

from __future__ import annotations

try:
    from apted import APTED
    from apted.helpers import Tree

    _HAS_APTED = True
except ImportError:  # pragma: no cover - exercised when apted missing
    APTED = None  # type: ignore[assignment,misc]
    Tree = None  # type: ignore[assignment,misc]
    _HAS_APTED = False

try:
    from rapidfuzz.distance import Levenshtein

    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover - exercised when rapidfuzz missing
    Levenshtein = None  # type: ignore[assignment,misc]
    _HAS_RAPIDFUZZ = False


def _levenshtein_distance(left: str, right: str) -> int:
    """Compute Levenshtein distance, preferring rapidfuzz when installed."""
    if _HAS_RAPIDFUZZ:
        return Levenshtein.distance(left, right)
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (left_char != right_char)
            current.append(min(insert_cost, delete_cost, replace_cost))
        previous = current
    return previous[-1]


def ned(pred: str, ref: str) -> float:
    """Normalized edit distance: Levenshtein / max(len). 0 if both empty."""
    if not pred and not ref:
        return 0.0
    distance = _levenshtein_distance(pred, ref)
    return distance / max(len(pred), len(ref))


def anls(pred: str, ref: str, tau: float = 0.5) -> float:
    """Return 1 - NED when NED is below tau, otherwise 0."""
    normalized = ned(pred, ref)
    if normalized < tau:
        return 1.0 - normalized
    return 0.0


def field_prf(pred: dict[str, str], ref: dict[str, str]) -> dict:
    """Exact-match precision, recall, F1, and micro F1 over field keys."""
    keys = set(pred) | set(ref)
    true_positives = sum(
        1 for key in keys if key in pred and key in ref and pred[key] == ref[key]
    )
    precision = true_positives / len(pred) if pred else 0.0
    recall = true_positives / len(ref) if ref else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    micro = f1
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "micro": micro,
    }


def _table_to_tree(rows: list[list[str]]):
    """Build an apted Tree for a table: ROOT -> ROW -> CELL -> text."""
    row_nodes = []
    for row in rows:
        cell_nodes = [Tree("CELL", Tree(str(cell))) for cell in row]
        row_nodes.append(Tree("ROW", *cell_nodes))
    return Tree("ROOT", *row_nodes)


def _count_nodes(node) -> int:
    """Count nodes in an apted Tree."""
    return 1 + sum(_count_nodes(child) for child in node.children)


def _cell_overlap_similarity(
    pred_rows: list[list[str]], ref_rows: list[list[str]]
) -> float:
    """Fallback table similarity using matched cell counts."""
    pred_cells = [cell for row in pred_rows for cell in row]
    ref_cells = [cell for row in ref_rows for cell in row]
    max_cells = max(len(pred_cells), len(ref_cells))
    if max_cells == 0:
        return 1.0
    matched = sum(
        1
        for index in range(min(len(pred_cells), len(ref_cells)))
        if pred_cells[index] == ref_cells[index]
    )
    return matched / max_cells


def teds(pred_rows: list[list[str]], ref_rows: list[list[str]]) -> float:
    """Tree-edit similarity for tables; 1.0 means identical structure and text."""
    if _HAS_APTED:
        pred_tree = _table_to_tree(pred_rows)
        ref_tree = _table_to_tree(ref_rows)
        distance = APTED(pred_tree, ref_tree).compute_edit_distance()
        max_nodes = max(_count_nodes(pred_tree), _count_nodes(ref_tree))
        if max_nodes == 0:
            return 1.0
        return 1.0 - (distance / max_nodes)
    return _cell_overlap_similarity(pred_rows, ref_rows)


def line_prf(pred_labels: list[str], ref_labels: list[str]) -> dict:
    """Per-line accuracy and F1 treating the 'quoted' label as positive."""
    pair_count = max(len(pred_labels), len(ref_labels))
    if pair_count == 0:
        return {"accuracy": 1.0, "f1_quoted": 0.0}

    accuracy_total = 0
    true_positives = 0
    false_positives = 0
    false_negatives = 0

    for index in range(pair_count):
        predicted = pred_labels[index] if index < len(pred_labels) else ""
        reference = ref_labels[index] if index < len(ref_labels) else ""
        if predicted == reference:
            accuracy_total += 1

        predicted_positive = predicted == "quoted"
        reference_positive = reference == "quoted"
        if predicted_positive and reference_positive:
            true_positives += 1
        elif predicted_positive and not reference_positive:
            false_positives += 1
        elif not predicted_positive and reference_positive:
            false_negatives += 1

    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else 0.0
    )
    f1_quoted = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    return {
        "accuracy": accuracy_total / pair_count,
        "f1_quoted": f1_quoted,
    }
