"""Backend execution: subprocess CLIs and OpenAI-compatible HTTP endpoints.

No third-party dependencies — HTTP goes through urllib on a worker thread so
the whole tool stays installable with nothing but the standard library.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request

from .config import Tier

__all__ = ["BackendError", "run_tier", "CHILD_ENV_VAR"]

# Set in the environment of every child process. A backend that is itself a
# tierlane-aware agent can read this and decline to delegate further, which is
# what stops two routers from bouncing a task between each other forever.
CHILD_ENV_VAR = "TIERLANE_CHILD"

PROMPT_PLACEHOLDER = "{prompt}"


class BackendError(Exception):
    """The backend failed to produce output."""


def _build_command(tier: Tier, prompt: str) -> tuple[list[str], str | None]:
    """Return (argv, stdin_text).

    If the configured command contains a {prompt} placeholder the prompt is
    substituted there; otherwise it is piped in on stdin, which avoids the
    command-line length limits that long contexts would otherwise hit.
    """
    if any(PROMPT_PLACEHOLDER in part for part in tier.command):
        argv = [part.replace(PROMPT_PLACEHOLDER, prompt) for part in tier.command]
        return argv, None
    return list(tier.command), prompt


async def _run_cli(tier: Tier, prompt: str, timeout: float) -> str:
    argv, stdin_text = _build_command(tier, prompt)

    env = os.environ.copy()
    env[CHILD_ENV_VAR] = "1"

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_text else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        raise BackendError(f"{tier.executable!r} is not installed or not on PATH.") from exc

    try:
        out_bytes, err_bytes = await asyncio.wait_for(
            proc.communicate(stdin_text.encode("utf-8") if stdin_text else None),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise BackendError(f"{tier.name} did not respond within {timeout:.0f}s.") from None

    stdout = out_bytes.decode("utf-8", errors="replace").strip()
    stderr = err_bytes.decode("utf-8", errors="replace").strip()

    # Some CLIs write warnings to stderr and still succeed, so a non-zero exit
    # only counts as failure when there is genuinely nothing on stdout.
    if proc.returncode != 0 and not stdout:
        raise BackendError(f"{tier.name} exited {proc.returncode}: {stderr[:500]}")
    if not stdout:
        raise BackendError(f"{tier.name} produced no output.")
    return stdout


def _post_chat(endpoint: str, model: str, prompt: str, timeout: float) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
    ).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("TIERLANE_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(endpoint, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise BackendError(f"{endpoint} returned HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise BackendError(f"Could not reach {endpoint}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise BackendError(f"{endpoint} did not return JSON: {exc}") from exc

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise BackendError(
            f"{endpoint} returned an unexpected response shape: {str(body)[:200]}"
        ) from exc

    text = (content or "").strip()
    if not text:
        raise BackendError(f"{tier_label(endpoint, model)} returned an empty message.")
    return text


def tier_label(endpoint: str, model: str) -> str:
    return f"{model or 'model'} at {endpoint}"


async def _run_http(tier: Tier, prompt: str, timeout: float) -> str:
    # urllib is blocking, so it goes to a worker thread to keep the event loop
    # free for the timeout and for any concurrent callers.
    return await asyncio.to_thread(_post_chat, tier.endpoint, tier.model, prompt, timeout)


async def run_tier(tier: Tier, prompt: str, timeout: float) -> str:
    """Execute `prompt` on `tier`. Raises BackendError on any failure."""
    if tier.kind == "http":
        return await _run_http(tier, prompt, timeout)
    return await _run_cli(tier, prompt, timeout)
