"""Two-stage local classification: embeddings shortlist, local LLM decides.

Everything runs on the user's machine:
- Stage 1: sentence-transformers embeds each message *with its neighbours*
  and compares it to the topic description and example messages.
- Stage 2: a local LLM served by Ollama (http://localhost:11434) reads each
  shortlisted message in context and returns a JSON verdict.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from .xmlio import Message


@dataclass
class TopicSpec:
    description: str            # plain-English description of what to remove
    positive_examples: list[str]  # messages that SHOULD be removed
    negative_examples: list[str]  # look-alikes that must be KEPT


@dataclass
class Verdict:
    index: int
    similarity: float
    shortlisted: bool
    remove: bool
    confidence: float
    reason: str


def load_topic(path: str) -> TopicSpec:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return TopicSpec(d["description"], d.get("positive_examples", []), d.get("negative_examples", []))


def context_window(messages: list[Message], i: int, size: int) -> tuple[list[Message], list[Message]]:
    """Messages before and after position i in chronological order."""
    return messages[max(0, i - size):i], messages[i + 1:i + 1 + size]


def _fmt(m: Message) -> str:
    who = "Me" if m.box == "sent" else "Them"
    return f"{who}: {m.text.strip() or '[no text]'}"


# ---------------------------------------------------------------- stage 1

def embedding_scores(messages: list[Message], topic: TopicSpec, window: int,
                     model_name: str) -> list[float]:
    from sentence_transformers import SentenceTransformer, util  # local model, downloaded once

    model = SentenceTransformer(model_name)
    queries = [topic.description] + topic.positive_examples
    negatives = topic.negative_examples

    def with_context(i: int) -> str:
        before, after = context_window(messages, i, window)
        return " | ".join(_fmt(m) for m in before + [messages[i]] + after)

    texts = [with_context(i) for i in range(len(messages))]
    own = [_fmt(m) for m in messages]

    q = model.encode(queries, normalize_embeddings=True, convert_to_tensor=True)
    t_ctx = model.encode(texts, normalize_embeddings=True, convert_to_tensor=True,
                         batch_size=64, show_progress_bar=True)
    t_own = model.encode(own, normalize_embeddings=True, convert_to_tensor=True,
                         batch_size=64, show_progress_bar=False)

    pos = 0.6 * util.cos_sim(t_own, q).max(dim=1).values + 0.4 * util.cos_sim(t_ctx, q).max(dim=1).values
    if negatives:
        n = model.encode(negatives, normalize_embeddings=True, convert_to_tensor=True)
        neg = util.cos_sim(t_own, n).max(dim=1).values
        pos = pos - 0.25 * neg.clamp(min=0)
    return [float(x) for x in pos]


# ---------------------------------------------------------------- stage 2

_PROMPT = """You review text messages from one conversation for a privacy clean-up.

TOPIC TO REMOVE:
{description}

Examples that belong to the topic:
{positives}

Examples that look similar but do NOT belong to the topic:
{negatives}

Conversation context (oldest first). The message being judged is marked >>> <<<.
{context}

Does the marked message express, refer to, or continue the topic above, even
without naming it directly (for example a reply that only makes sense as part
of that topic)? Judge the marked message only; context is for understanding.

Answer with JSON only: {{"remove": true|false, "confidence": 0.0-1.0, "reason": "<one short sentence>"}}"""


def llm_verdict(messages: list[Message], i: int, topic: TopicSpec, window: int,
                model: str, host: str) -> tuple[bool, float, str]:
    before, after = context_window(messages, i, window)
    lines = [_fmt(m) for m in before] + [f">>> {_fmt(messages[i])} <<<"] + [_fmt(m) for m in after]
    prompt = _PROMPT.format(
        description=topic.description,
        positives="\n".join(f"- {p}" for p in topic.positive_examples) or "- (none given)",
        negatives="\n".join(f"- {p}" for p in topic.negative_examples) or "- (none given)",
        context="\n".join(lines),
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }).encode("utf-8")
    req = urllib.request.Request(f"{host}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        content = json.loads(r.read())["message"]["content"]
    try:
        d = json.loads(content)
        return bool(d.get("remove")), float(d.get("confidence", 0)), str(d.get("reason", ""))[:300]
    except (ValueError, TypeError):
        return False, 0.0, f"unparseable model reply: {content[:120]}"
