"""Summarise viewer questions/suggestions via an OpenAI-compatible chat completions endpoint."""

import json
import re

import httpx

from .models import Message, SummaryItem, SummaryResponse
from .settings import Settings

SYSTEM_PROMPT = """You analyse Instagram direct messages sent to a content creator whose videos are aimed at
business people and technologists. Your job is to extract useful VIDEO IDEAS from the viewers' messages.

Instructions:
1. Read every message. Ignore chit-chat, thanks, spam, promotion, and messages from the creator themself.
2. Identify each QUESTION (something a viewer wants explained) and each SUGGESTION (a topic or format a viewer
   wants covered).
3. DEDUPLICATE: if several messages ask essentially the same thing, merge them into ONE item. The item's "count"
   is the number of DISTINCT VIEWERS (senders) who expressed it - several messages from the same viewer count
   once. "message_ids" must list ALL messages expressing it, from every viewer.
4. Every item must cite at least one message id. Only use ids that appear in the input. Never invent ids.
5. Write "title" as a short, punchy video idea (max 12 words) and "summary" as one or two sentences explaining
   what viewers want to know and why it would make a good video.
6. Order items by count descending.

Respond with ONLY a JSON object in this exact shape:
{
  "overview": "one or two sentences summarising the overall themes",
  "items": [
    {"kind": "question" | "suggestion", "title": "...", "summary": "...", "count": 3, "message_ids": ["m1", "m4", "m9"]}
  ]
}"""


class LLMError(Exception):
    pass


async def summarise(settings: Settings, messages: list[Message]) -> SummaryResponse:
    viewer_messages = [m for m in messages if not m.from_me]
    if not viewer_messages:
        return SummaryResponse(items=[], overview="No viewer messages selected.", messages_considered=0, model=settings.llm_model)

    ref_to_id: dict[str, str] = {}
    id_to_sender: dict[str, str] = {}
    lines = []
    for i, m in enumerate(sorted(viewer_messages, key=lambda x: x.created_time), start=1):
        ref = f"m{i}"
        ref_to_id[ref] = m.id
        sender = m.sender_username or m.sender_id or "viewer"
        id_to_sender[m.id] = m.sender_id or sender
        text = " ".join(m.text.split())
        lines.append(f"[{ref}] @{sender} ({m.created_time:%Y-%m-%d}): {text}")

    user_prompt = "Messages:\n" + "\n".join(lines) + "\n\nReturn the JSON object now."
    raw = await _chat(settings, SYSTEM_PROMPT, user_prompt)
    parsed = _extract_json(raw)

    items: list[SummaryItem] = []
    for it in parsed.get("items", []):
        ids = []
        for ref in it.get("message_ids", []) or []:
            ref = str(ref).strip()
            if ref in ref_to_id:
                ids.append(ref_to_id[ref])
            elif ref in ref_to_id.values():
                ids.append(ref)
        ids = list(dict.fromkeys(ids))
        if not ids:
            continue
        kind = str(it.get("kind", "suggestion")).lower()
        items.append(
            SummaryItem(
                kind="question" if kind.startswith("q") else "suggestion",
                title=str(it.get("title", "")).strip() or "Untitled idea",
                summary=str(it.get("summary", "")).strip(),
                count=max(len({id_to_sender[i] for i in ids}), 1),
                message_ids=ids,
            )
        )
    items.sort(key=lambda x: x.count, reverse=True)
    return SummaryResponse(
        items=items,
        overview=str(parsed.get("overview", "")).strip(),
        messages_considered=len(viewer_messages),
        model=settings.llm_model,
    )


async def _chat(settings: Settings, system: str, user: str) -> str:
    url = settings.llm_base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
    body = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    # Progressively drop optional parameters that some endpoints/models reject
    # (reasoning models only accept the default temperature; some servers lack response_format).
    variants = [
        {**body, "temperature": 0.2, "response_format": {"type": "json_object"}},
        {**body, "response_format": {"type": "json_object"}},
        {**body, "temperature": 0.2},
        body,
    ]
    async with httpx.AsyncClient(timeout=180) as client:
        for payload in variants:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 400:
                break
        if resp.status_code >= 400:
            raise LLMError(f"LLM endpoint returned {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected LLM response shape: {json.dumps(data)[:500]}") from e
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMError(f"LLM did not return valid JSON: {text[:300]}")
