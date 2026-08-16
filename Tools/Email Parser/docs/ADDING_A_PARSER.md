# Adding a Parser

This guide walks through the built-in plain-text parser as a template for new format handlers.

## Protocol

Every parser implements the frozen contract in `email_parser/file_parsers/base.py`:

| Member | Type | Purpose |
|--------|------|---------|
| `name` | `str` | Stable parser id (e.g. `text_plain`) |
| `version` | `str` | Parser version string stored in provenance |
| `priority` | `int` | Higher wins when multiple parsers claim the same blob |
| `can_handle(mime_type, sniffed)` | method | Return `True` when this parser should run; use magic bytes, not file extensions |
| `parse(blob, ctx)` | method | Return `ParseResult(document, child_blobs=[])` |

Supporting types:

- **`Blob`** — `raw`, optional `filename`, `mime_type`, `relation_to_parent`, `ordinal`, `content_id`
- **`ParseContext`** — `max_depth`, `max_fanout`, `depth`, `parent_id`, `root_id`, `pdf_engine`
- **`ParseResult`** — one `Document` plus zero or more child `Blob` objects for the pipeline to enqueue

**Rules**

- Do not recurse into the pipeline or call other parsers from `parse()`.
- Do not import PyMuPDF or other engine types into `base.py` or leak them through the protocol.
- Emit `Document` models from `email_parser.models` only.

## Entry point registration

Register in `pyproject.toml`:

```toml
[project.entry-points."email_parser.parsers"]
my_format = "my_package.my_parser:MyFormatParser"
```

Built-in parsers (`email_mime`, `pdf_pymupdf`, `text_plain`) are always merged in `registry.load_parsers()` so tests work without an editable install. Third-party entry points load via `importlib.metadata.entry_points(group="email_parser.parsers")`.

For tests, use `register_parser()` from `email_parser.file_parsers.registry`.

## Worked example: `text_plain.py`

### 1. Claim blobs in `can_handle`

```python
def can_handle(self, mime_type: str, sniffed: bytes) -> bool:
    lowered = (mime_type or "").lower()
    if lowered == "text/plain" or lowered.startswith("text/plain"):
        return True
    return _looks_like_ascii_text(sniffed)
```

Reject email sniff patterns and PDF magic so `email_mime` and `pdf_pymupdf` keep priority.

### 2. Build a content-addressed document

```python
doc_id = make_doc_id(blob.raw)
```

Never use random ids or timestamps in `doc_id` or `block_id`. Use `make_block_id(doc_id, ordinal, block_type)`.

### 3. Emit blocks

Split text into paragraphs; attach anchors when geometry exists (plain text uses empty `Anchor()` placeholders):

```python
Block(
    block_id=make_block_id(doc_id, ordinal, BlockType.paragraph.value),
    type=BlockType.paragraph,
    text=paragraph,
    anchor=Anchor(),
)
```

### 4. Fill metadata and provenance

```python
metadata=DocumentMetadata(
    common=CommonMetadata(filename=blob.filename, byte_size=len(blob.raw)),
),
provenance=Provenance(
    parser=self.name,
    parser_version=self.version,
    parsed_at=None,
    status=ParseStatus.ok,
),
```

Parsed header facts belong in `metadata`. Do not populate `extractions` during parse.

### 5. Return children separately

Plain text has no nested files:

```python
return ParseResult(document=document, child_blobs=[])
```

For a container format, return attachment bytes as new `Blob` instances:

```python
child_blobs.append(
    Blob(
        raw=payload_bytes,
        filename=filename,
        mime_type=part_content_type,
        relation_to_parent=RelationType.attachment,
        ordinal=index,
    )
)
```

The pipeline assigns `parent_id`, increments `depth`, enforces `max_fanout` and `max_depth`, and deduplicates identical byte hashes.

## Checklist for a new parser

1. Add `my_parser.py` under `email_parser/file_parsers/` (or your package).
2. Implement `Parser` with `can_handle` based on sniffed bytes.
3. Map content to `Block` list with appropriate `BlockType` values.
4. Set `source_type` and `mime_type` on `Document`.
5. Return child blobs instead of calling `process()`.
6. Register entry point in `pyproject.toml`.
7. Add unit tests under `tests/` with fixture bytes and invariant checks.

## Testing

```bash
uv run pytest tests/test_registry.py tests/test_plugin_swap.py -q
```

Use `register_parser()` to inject a fake parser and assert dispatch order and isolation from built-ins.
