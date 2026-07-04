"""Chat-template filling and LLM-response parsing helpers."""

from __future__ import annotations

import copy
import json
import re
import textwrap
from typing import Any


def format_chat(chat: list[dict], **kwargs) -> list[dict]:
    """Deep-copy ``chat`` and fill the last message's ``{placeholders}`` with ``kwargs``."""
    new_chat = copy.deepcopy(chat)
    new_chat[-1]["content"] = new_chat[-1]["content"].format(**kwargs)
    return new_chat


def format_random_chat(chat: list[dict], args: list[dict]) -> list[dict]:
    """Like :func:`format_chat`, but fill each message with the matching dict in ``args``."""
    new_chat = copy.deepcopy(chat)
    for idx, arg in enumerate(args):
        new_chat[idx]["content"] = new_chat[idx]["content"].format(**arg)
    return new_chat


def format_response_split(message: str) -> list[str]:
    """Strip numbers / punctuation and split into items, mimicking the original behavior."""
    message = re.sub(r"[\d.]+", "", message)
    return re.split(r",|\n", message)


def print_message(message: str) -> str:
    """Pass-through that also prints, kept for pipeline-side debugging."""
    print(message)
    return message


def format_response_json(text: str) -> Any:
    """Extract the JSON object from a ```json ...``` fenced block."""
    sql_match = re.search(r"```json(.*?)```", text, re.DOTALL)
    if sql_match:
        try:
            return json.loads(sql_match.group(1))
        except json.JSONDecodeError:
            print(text)
            raise Exception("Invalid JSON")
    raise Exception("No JSON block found")


def format_response_strip(text: str) -> str:
    return text.strip()


def format_response_quote(text: str) -> str:
    """Extract content from a generic triple-backtick fenced block."""
    sql_match = re.search(r"```(.*?)```", text, re.DOTALL)
    if sql_match:
        result = sql_match.group(1).strip()
        if not result:
            print(text)
            raise Exception("No message found")
        return result
    raise Exception("No message found")


def format_response_sql(text: str) -> str:
    """Best-effort SQL extraction from an LLM response.

    Tries (in order): a ```sql ...``` block, any ``` ... ``` block, and finally
    a heuristic that captures the first SELECT-prefixed clause. Empty input is
    coerced to ``SELECT 'Hello, World!';`` to keep downstream callers happy.
    """
    sql_matches = re.findall(r"```sql(.*?)```", text, re.DOTALL)
    if sql_matches:
        return sql_matches[-1].strip()

    sql_match = re.search(r"```(.*?)```", text, re.DOTALL)
    if sql_match:
        return sql_match.group(1).strip()

    text = text if text.strip() else "SELECT 'Hello, World!';"

    text = text.split(":")[-1]
    text = text.strip().split("#", 1)[0].split(";", 1)[0]
    if "select" in text.split("(")[0].lower():
        match = re.search(r"(select.*)", text, re.IGNORECASE | re.DOTALL)
        text = match.group(1) if match else text

    if text.strip().lower().startswith("select"):
        return text.replace("```", "").strip()
    return "SELECT " + text.replace("```", "").strip()


def format_csv_path(csv_paths: list[str]) -> str:
    """Concatenate CSV paths into a newline-separated block."""
    result = ""
    for csv_path in csv_paths:
        result += f"\n {csv_path}\n"
    return result


def format_response_python_code(text: str) -> str:
    """Extract the first ```python ...``` block, dedented."""
    code_match = re.search(r"(```python\s*.*?\s*```)", text, re.DOTALL)
    code_match = code_match.group(1) if code_match else ""
    code_match = code_match.replace("```python\n", "").replace("```", "")
    if code_match:
        return textwrap.dedent(code_match).strip()
    return ""


def format_output(result: Any) -> str:
    """Truncate long results to a human-readable preview string (mirror of database.format_output)."""
    if isinstance(result, int):
        return str(result)
    if isinstance(result, str):
        if len(result) > 300:
            return f"{result[:150]}...{result[-150:]} (length: {len(result)})"
        return result
    if isinstance(result, list):
        if len(result) > 10:
            return (
                f"total length: {len(result)}, and the first 5 and the last 5 lines are: "
                f"{format_output(str(result[:5]))} ... {format_output(result[-5:])}"
            )
        return format_output(str(result))
    s = str(result)
    if len(s) > 300:
        return f"{s[:150]}...{s[-150:]} (length: {len(s)})"
    return s
