# Metrics

Three tiers separate operational run stats (A), unlabeled health signals (B), and labeled accuracy (C). CLI `email-parser metrics` prints Tier A + B. Tier C is used in tests against `.truth.json` sidecars.

## Tier A — Run metrics

Source: `email_parser/metrics/run_metrics.py`

| Name | Definition | Source | Range | Good score |
|------|------------|--------|-------|------------|
| `tier` | Literal `"A"` | internal | — | `"A"` |
| `accepted` | Documents with status `ok` or `warning` | internal | 0 … N | Higher |
| `rejected` | Externally rejected inputs (optional counter) | internal | 0 … N | Lower |
| `deduped` | Duplicate byte payloads skipped in pipeline | internal | 0 … N | Context-dependent |
| `emails_parsed` | Documents with `source_type=email` | internal | 0 … N | Matches input `.eml` count |
| `attachments_by_type` | Child documents grouped by MIME type | internal | map | Complete coverage |
| `docs_produced` | Total documents including attachments | internal | ≥ roots | Matches tree size |
| `max_depth` | Deepest `depth` field observed | internal | 0 … cap | Within cap |
| `elapsed_s` | Wall time for parse loop | internal | ≥ 0 | Lower (throughput) |
| `failures_by_status` | Counts by `provenance.status` | internal | map | More `ok`, fewer `failed` |
| `partial_successes` | Root emails `ok`/`warning` with a failed/unsupported descendant | internal | 0 … N | Lower |

## Tier B — Health metrics

Source: `email_parser/metrics/health_metrics.py`

| Name | Definition | Source | Range | Good score |
|------|------------|--------|-------|------------|
| `tier` | Literal `"B"` | internal | — | `"B"` |
| `chars_per_page_avg` | Mean characters per PDF page from `metadata.native.chars_per_page` | internal | ≥ 0 | Stable across corpus |
| `anchor_coverage` | Fraction of blocks with valid anchors for their source type | internal | 0.0 … 1.0 | Higher (PDFs near 1.0) |
| `quoted_text_ratio` | Chars in `quoted_history` / total block chars | internal | 0.0 … 1.0 | Matches thread-heavy corpora |
| `cid_resolution_rate` | `image_ref` blocks whose `child_doc_id` exists / total `image_ref` | internal | 0.0 … 1.0 | 1.0 |
| `invariant_violations` | Structural rule breaks (orphan parents, duplicate block ids, missing PDF bboxes) | internal | list | Empty list |

## Tier C — Accuracy metrics

Source: `email_parser/metrics/accuracy_metrics.py`. Used with labeled synthetic `.truth.json` fixtures.

| Name | Definition | Source paper | Range | Good score |
|------|------------|--------------|-------|------------|
| `ned` | Normalized edit distance: Levenshtein / max(len(pred), len(ref)); 0 if both empty | Classic string metric | 0.0 … 1.0 | 0.0 (lower is better) |
| `anls` | Average Normalized Levenshtein Similarity: if NED < τ then 1 − NED else 0 | ST-VQA (Biten et al., 2019), τ = 0.5 | 0.0 … 1.0 | 1.0 |
| `teds` | Tree Edit Distance-based Similarity for tables: 1 − edit_distance / max(nodes) | PubTabNet (Zhong et al., 2019) | 0.0 … 1.0 | 1.0 |
| `field_prf` | Exact-match precision, recall, F1, micro-F1 over metadata field dicts | Information extraction convention | per-field 0 … 1 | F1 → 1.0 |
| `line_prf` | Per-line label accuracy and F1 for quoted vs non-quoted labels | Reply/quote detection tasks | accuracy, `f1_quoted` 0 … 1 | Higher |

### ANLS detail

Implementation: `anls(pred, ref, tau=0.5)` in `accuracy_metrics.py`.

- Compute NED between prediction and reference strings.
- If NED < τ (default 0.5), score is `1 - NED`.
- Otherwise score is `0`.

This matches the ST-VQA relaxed accuracy used for scene text QA evaluation (Biten et al., ICDAR 2019 / TPAMI follow-ups).

### TEDS detail

Requires `apted` (dev dependency). Builds a tree: ROOT → ROW → CELL → text. Falls back to cell-overlap similarity when `apted` is not installed.

### Line-level P/R/F1

`line_prf(pred_labels, ref_labels)` treats label `"quoted"` as the positive class for quote-boundary evaluation on reply fixtures (`reply_thread`).

## Web job metrics

The FastAPI job runner (`web/jobs.py`) writes a lighter `metrics.json` per job:

| Key | Meaning |
|-----|---------|
| `files` | Staged upload count |
| `documents` | Total documents produced |
| `root_emails` | Root email count |
| `status_counts` | Map of provenance status → count |
| `max_depth` | Deepest nesting |

Compare runs with:

```bash
uv run email-parser compare output/runs/JOB_A output/runs/JOB_B
```

## References

- Biten, A. et al. “Scene Text Visual Question Answering.” ICDAR 2019 (ANLS, τ = 0.5).
- Zhong, S. et al. “PubTabNet: Image-Based Table Recognition.” (TEDS for table structure).
- Internal invariant rules: `health_metrics.check_invariants()`.
