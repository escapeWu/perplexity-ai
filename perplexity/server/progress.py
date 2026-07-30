"""Normalize Perplexity workflow steps for optional OpenAI stream extensions."""

from typing import Any, Dict, Optional


_PROGRESS_STAGES = {
    "INITIAL_QUERY": ("initial_query", "Analyzing question"),
    "SEARCH_WEB": ("search_web", "Searching the web"),
    "SEARCH_RESULTS": ("search_results", "Reviewing sources"),
    "FINAL": ("final", "Writing answer"),
}


def _normalize_progress_step(step: Any) -> Optional[Dict[str, Any]]:
    """Convert one upstream step into the public, allow-listed progress schema."""
    if not isinstance(step, dict):
        return None

    upstream_stage = step.get("step_type")
    stage_config = _PROGRESS_STAGES.get(upstream_stage)
    if stage_config is None:
        return None

    stage, label = stage_config
    event: Dict[str, Any] = {"stage": stage, "label": label}
    content = step.get("content")
    if not isinstance(content, dict):
        return event

    detail: Dict[str, Any] = {}
    if upstream_stage == "SEARCH_WEB":
        queries = content.get("queries")
        if isinstance(queries, list):
            safe_queries = [
                query.strip()[:300] for query in queries if isinstance(query, str) and query.strip()
            ][:8]
            if safe_queries:
                detail["queries"] = safe_queries
                detail["query_count"] = len(safe_queries)
    elif upstream_stage == "SEARCH_RESULTS":
        web_results = content.get("web_results")
        if isinstance(web_results, list):
            detail["source_count"] = len(web_results)

    if detail:
        event["detail"] = detail
    return event


class ProgressTracker:
    """Turn cumulative upstream step snapshots into ordered lifecycle events."""

    def __init__(self) -> None:
        self._events: Dict[str, Dict[str, Any]] = {}
        self._active_key: Optional[str] = None
        self._next_id = 1

    def update(self, upstream_chunk: Dict[str, Any]) -> list[Dict[str, Any]]:
        text = upstream_chunk.get("text")
        if not isinstance(text, list):
            return []

        updates = []
        for step in text:
            normalized = _normalize_progress_step(step)
            if normalized is None:
                continue

            # Public progress stages are unique lifecycle phases. Keying by the
            # upstream list index made repeated SEARCH_RESULTS snapshots appear
            # as duplicate UI steps when the upstream reordered its payload.
            key = normalized["stage"]
            existing = self._events.get(key)
            if existing is not None:
                new_detail = normalized.get("detail")
                if new_detail is not None and new_detail != existing.get("detail"):
                    existing["detail"] = new_detail
                    updates.append(dict(existing))
                continue

            if self._active_key is not None:
                active = self._events[self._active_key]
                if active["status"] == "running":
                    active["status"] = "completed"
                    updates.append(dict(active))

            event = {
                "id": f"progress-{self._next_id}",
                **normalized,
                "status": "running",
            }
            self._next_id += 1
            self._events[key] = event
            self._active_key = key
            updates.append(dict(event))

        return updates

    def finish(self, status: str) -> Optional[Dict[str, Any]]:
        if self._active_key is None:
            return None
        active = self._events[self._active_key]
        if active["status"] != "running":
            return None
        active["status"] = status
        return dict(active)


def make_progress_chunk(
    response_id: str,
    created: int,
    model_id: str,
    progress: Dict[str, Any],
) -> Dict[str, Any]:
    """Wrap a progress event in an OpenAI-compatible streaming chunk."""
    return {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": None,
            }
        ],
        "perplexity_progress": progress,
    }
