"""OpenAI-compatible chat client used by every SAGE agent.

The client wraps the OpenAI Python SDK while keeping the runtime endpoint,
model name, and API key configurable. Self-hosted vLLM and sglang servers can
use the ``localModel`` fallback key, while remote OpenAI-compatible endpoints
can rely on ``SAGE_LLM_API_KEY`` or ``OPENAI_API_KEY``.

``GPTChat`` remains available as a compatibility alias for older scripts.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from openai import OpenAI


def _resolve_api_key(explicit: str | None) -> str:
    """Pick an API key, in order: explicit arg → env var → ``localModel`` fallback."""
    if explicit:
        return explicit
    env_key = os.environ.get("SAGE_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    return env_key or "localModel"


class LLMClient:
    """A thin wrapper around the OpenAI Python SDK's chat-completions endpoint.

    The instance owns a conversation history (``self.messages``) so callers can
    use it either in stateless mode (:meth:`chat_with_llm_only` — pass an
    explicit message list each time) or stateful mode (:meth:`chat_with_llm` —
    appends to ``self.messages``).
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/v1",
        model: str = "localModel",
        api_key: str | None = None,
        timeout: float = 60 * 60 * 3,
        **default_args: Any,
    ) -> None:
        self.client = OpenAI(
            base_url=base_url,
            api_key=_resolve_api_key(api_key),
            timeout=timeout,
        )
        self.model = model
        self.messages: list[dict] = []
        self.default_args: dict[str, Any] = {}
        self.default_args.update(default_args)
        # vLLM-specific extras — kept here so per-call args can still extend
        # them via ``extra_body=...``.
        self.default_args.setdefault("extra_body", {})

    # ------------------------------------------------------------------
    # Stateless: caller supplies the full prompt every time.
    # ------------------------------------------------------------------
    def chat_with_llm_only(
        self,
        prompt: list[dict],
        format_fuc: Callable[[str], Any] | None = None,
        max_retry: int = 5,
        **args: Any,
    ) -> list[Any]:
        """Send ``prompt`` and return the choices, optionally post-processed.

        Retries up to ``max_retry`` times on any exception (network errors,
        rate limits, etc.). On final failure, raises ``RuntimeError``.
        """
        args = {**self.default_args, **args}
        last_error: Exception | None = None
        for attempt in range(1, max_retry + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=prompt,
                    **args,
                )
                if format_fuc:
                    return [format_fuc(item.message.content) for item in response.choices]
                return [item.message.content for item in response.choices]
            except Exception as e:
                last_error = e
                if attempt == max_retry:
                    raise RuntimeError(f"LLM call failed after {max_retry} attempts: {e}") from e
                print(f"[Retry {attempt}/{max_retry}] LLM error: {e}.")
        # Unreachable, but keeps type checkers happy.
        raise RuntimeError(f"LLM call failed: {last_error}")

    # ------------------------------------------------------------------
    # Stateful: appends to / consumes self.messages.
    # ------------------------------------------------------------------
    def chat_with_llm(
        self,
        messages: list[dict] | str,
        format_fuc: Callable[[str], Any] | None = None,
        **args: Any,
    ) -> list[Any]:
        """Append ``messages`` to history (or replace history if a list) and complete."""
        if isinstance(messages, list):
            self.messages = messages
        else:
            self.messages.append({"role": "user", "content": messages})
        args = {**self.default_args, **args}

        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            **args,
        )
        self.messages.append(
            {"role": "assistant", "content": response.choices[0].message.content}
        )

        if format_fuc:
            return [format_fuc(item.message.content) for item in response.choices]
        return [item.message.content for item in response.choices]

    def clear_history(self) -> None:
        self.messages = []

    def init_history(self, messages: list[dict]) -> None:
        self.messages = messages


# Backward-compat alias.
GPTChat = LLMClient


def build_client(server_config: dict[str, Any], **extra: Any) -> LLMClient:
    """Construct an :class:`LLMClient` from a ``configs/default.yaml``-style block.

    Example::

        from sage.config import load_config
        from sage.server import build_client
        cfg = load_config("configs/default.yaml")
        attacker = build_client(cfg["servers"]["attacker"], temperature=0.6)
    """
    return LLMClient(
        base_url=server_config.get("base_url", "http://127.0.0.1:8000/v1"),
        model=server_config.get("model", "localModel"),
        api_key=server_config.get("api_key"),
        **extra,
    )
