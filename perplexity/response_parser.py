"""Normalize evolving Perplexity ``/ask`` streaming payloads."""

from typing import Any, Dict, List, Optional


class UpstreamResponseAccumulator:
    """Restore stable answer, source, and workflow fields from block responses.

    Perplexity's newer response shape sends answer text through ``blocks``.
    Intermediate markdown events may contain a complete chunk snapshot
    (``chunk_starting_offset == 0``) or only chunks appended after an offset.
    This accumulator rebuilds a cumulative answer for existing callers and
    exposes synthetic legacy workflow steps so progress streaming keeps working.
    """

    _WORKFLOW_ORDER = (
        "INITIAL_QUERY",
        "SEARCH_WEB",
        "SEARCH_RESULTS",
        "FINAL",
    )

    def __init__(self) -> None:
        self._answer_chunks: List[str] = []
        self._workflow_steps: List[Dict[str, Any]] = []

    def normalize(self, response: Dict[str, Any]) -> Dict[str, Any]:
        blocks = response.get("blocks")
        if not isinstance(blocks, list):
            return response

        self._ensure_workflow_step("INITIAL_QUERY")
        has_legacy_workflow = isinstance(response.get("text"), list)

        for block in blocks:
            if not isinstance(block, dict):
                continue

            web_result_block = block.get("web_result_block")
            if isinstance(web_result_block, dict):
                self._normalize_web_results(response, web_result_block)

            markdown_block = block.get("markdown_block")
            if isinstance(markdown_block, dict):
                self._normalize_markdown(response, markdown_block)

        if not has_legacy_workflow:
            response["text"] = [
                {"step_type": step["step_type"], "content": dict(step["content"])}
                for step in self._workflow_steps
            ]

        return response

    def _normalize_web_results(
        self,
        response: Dict[str, Any],
        web_result_block: Dict[str, Any],
    ) -> None:
        web_results = web_result_block.get("web_results")
        if not isinstance(web_results, list):
            return

        self._ensure_workflow_step("SEARCH_WEB")
        self._ensure_workflow_step("SEARCH_RESULTS", {"web_results": web_results})
        # ``chunks`` is the stable source fallback consumed by server.app.
        response["chunks"] = web_results

    def _normalize_markdown(
        self,
        response: Dict[str, Any],
        markdown_block: Dict[str, Any],
    ) -> None:
        self._ensure_workflow_step("FINAL")

        chunks = markdown_block.get("chunks")
        if isinstance(chunks, list):
            text_chunks = [chunk for chunk in chunks if isinstance(chunk, str)]
            offset = self._non_negative_int(markdown_block.get("chunk_starting_offset"))
            if offset == 0:
                self._answer_chunks = text_chunks
            elif offset <= len(self._answer_chunks):
                end = offset + len(text_chunks)
                self._answer_chunks[offset:end] = text_chunks
            else:
                # A missing prefix should not make already delivered text vanish.
                self._answer_chunks.extend(text_chunks)

        explicit_answer = markdown_block.get("answer")
        if isinstance(explicit_answer, str) and explicit_answer:
            response["answer"] = explicit_answer
        elif self._answer_chunks:
            response["answer"] = "".join(self._answer_chunks)

    def _ensure_workflow_step(
        self,
        step_type: str,
        content: Optional[Dict[str, Any]] = None,
    ) -> None:
        for step in self._workflow_steps:
            if step["step_type"] == step_type:
                if content is not None:
                    step["content"] = content
                return
        self._workflow_steps.append(
            {
                "step_type": step_type,
                "content": content or {},
            }
        )
        self._workflow_steps.sort(key=lambda step: self._WORKFLOW_ORDER.index(step["step_type"]))

    @staticmethod
    def _non_negative_int(value: Any) -> int:
        return value if isinstance(value, int) and value >= 0 else 0
