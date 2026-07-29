# Changelog

## [1.12.0] - 2026-07-29

### Added

- Added opt-in structured progress chunks to OpenAI-compatible streaming responses.
- Added a live stage timeline to the Playground for query analysis, web search, source review, and answer generation.

### Fixed

- Preserved partial streamed output and stage state when requests fail or are cancelled.
- Aligned synchronous and asynchronous Perplexity requests with the browser `query_source` field required by current models.

## [Unreleased] - 2025-12-02

### Fixed

#### Bug #1: Missing Import
- Added the missing `time` import in `perplexity/emailnator.py`.

#### Bug #2: Response Parsing Returned `None`
- Updated the parsing logic to follow the new three-level JSON structure returned by the API.
- Extracted the `answer` field from the `FINAL` step payload.
- Captured `chunks` so streaming consumers can reconstruct the answer.
- Wrapped the parsing flow with defensive `try/except` blocks to avoid crashes.
- Added field validation before accessing nested data.
- Ensured that empty chunk lists now return an empty dictionary instead of `None`.

### Changed
- Updated the synchronous client's `stream_response()` method to use the new parser.
- Updated synchronous chunk iteration to surface parsed answers consistently.
- Updated the asynchronous client's `stream_response()` method to mirror the new parser.
- Updated asynchronous chunk iteration for consistent behavior with the sync client.

### Tested
- Manual Emailnator account creation
- Basic unauthenticated searches
- Streaming search (79 chunks)
- Follow-up searches
- Text file upload
- Asynchronous client issuing three queries in parallel
