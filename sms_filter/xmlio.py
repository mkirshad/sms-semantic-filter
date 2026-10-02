"""Byte-preserving reader/writer for SMS Backup & Restore XML files.

The app writes emoji as UTF-16 surrogate pairs (e.g. ``&#55357;&#56832;``),
which strict XML parsers reject or silently rewrite. Re-serialising the whole
document through a parser is therefore risky. Instead we:

1. scan the original text for top-level ``<sms .../>`` and ``<mms>...</mms>``
   entries (quote-aware, so ``>`` inside a message body is handled),
2. parse each entry on its own only to read its fields,
3. remove flagged entries by cutting their exact character spans out of the
   original text and updating the root ``count`` attribute.

Every byte that belongs to a kept message is left exactly as the app wrote it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

_SURROGATE_PAIR = re.compile(r"&#(5[5-6]\d{3});&#(5[6-7]\d{3});")
_ROOT_TAG = re.compile(r"<smses\b[^>]*>")
_COUNT_ATTR = re.compile(r'(\bcount=")(\d+)(")')


@dataclass
class Message:
    index: int          # position in the file (0-based)
    kind: str           # "sms" or "mms"
    start: int          # character span in the original text
    end: int
    date: int           # epoch milliseconds
    box: str            # "received" / "sent" / other
    address: str
    contact: str
    readable_date: str
    text: str
    attrs: dict = field(default_factory=dict)


def _decode_surrogates(fragment: str) -> str:
    """Turn surrogate-pair character references into real characters so lxml can parse."""
    def repl(m: re.Match) -> str:
        hi, lo = int(m.group(1)), int(m.group(2))
        if 0xD800 <= hi <= 0xDBFF and 0xDC00 <= lo <= 0xDFFF:
            return chr(0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00))
        return m.group(0)
    return _SURROGATE_PAIR.sub(repl, fragment)


def _scan_tag_end(text: str, pos: int) -> int:
    """Return the index just after the '>' that closes the tag starting at pos (quote-aware)."""
    quote = None
    i = pos
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ">":
            return i + 1
        i += 1
    raise ValueError(f"Unterminated tag starting at character {pos}")


def _find_entries(text: str):
    """Yield (kind, start, end) for each top-level sms/mms entry in document order."""
    pos = 0
    sms_re = re.compile(r"<(sms|mms)\b")
    while True:
        m = sms_re.search(text, pos)
        if not m:
            return
        kind, start = m.group(1), m.start()
        tag_end = _scan_tag_end(text, start)
        if kind == "sms" or text[tag_end - 2] == "/":
            end = tag_end
        else:
            close = text.find("</mms>", tag_end)
            if close == -1:
                raise ValueError(f"<mms> at character {start} has no closing tag")
            end = close + len("</mms>")
        # include the line break / indentation that follows, so removal leaves no blank line
        while end < len(text) and text[end] in "\r\n":
            end += 1
        yield kind, start, end
        pos = end


_BOX = {"1": "received", "2": "sent", "3": "draft", "4": "outbox", "5": "failed", "6": "queued"}
_MMS_BOX = {"1": "received", "2": "sent"}


def read_backup(path: str) -> tuple[str, list[Message]]:
    """Read the file as text and return (original_text, messages)."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    if not _ROOT_TAG.search(text):
        raise ValueError("Not an SMS Backup & Restore file: <smses> root element not found")

    messages: list[Message] = []
    for idx, (kind, start, end) in enumerate(_find_entries(text)):
        el = etree.fromstring(_decode_surrogates(text[start:end].strip()).encode("utf-8"))
        a = dict(el.attrib)
        if kind == "sms":
            body = a.get("body", "")
            box = _BOX.get(a.get("type", ""), a.get("type", ""))
        else:
            parts = [p.get("text", "") for p in el.iter("part")
                     if p.get("ct") == "text/plain" and p.get("text") not in (None, "null")]
            body = "\n".join(parts)
            box = _MMS_BOX.get(a.get("msg_box", ""), a.get("msg_box", ""))
        messages.append(Message(
            index=idx, kind=kind, start=start, end=end,
            date=int(a.get("date", "0") or 0), box=box,
            address=a.get("address", ""), contact=a.get("contact_name", ""),
            readable_date=a.get("readable_date", ""), text=body, attrs=a,
        ))
    return text, messages


def remove_messages(text: str, messages: list[Message], remove_indexes: set[int]) -> str:
    """Cut the flagged entries out of the original text and update the root count."""
    out, last = [], 0
    for m in messages:
        if m.index in remove_indexes:
            out.append(text[last:m.start])
            last = m.end
    out.append(text[last:])
    result = "".join(out)

    kept = len(messages) - len(remove_indexes)
    root = _ROOT_TAG.search(result)
    new_root = _COUNT_ATTR.sub(lambda m: f"{m.group(1)}{kept}{m.group(3)}", root.group(0), count=1)
    return result[:root.start()] + new_root + result[root.end():]


def verify(original_text: str, original_msgs: list[Message], output_path: str,
           removed: set[int]) -> list[str]:
    """Re-read the output and check it is exactly the original minus the removed entries."""
    problems = []
    out_text, out_msgs = read_backup(output_path)

    expected = [m for m in original_msgs if m.index not in removed]
    if len(out_msgs) != len(expected):
        problems.append(f"expected {len(expected)} messages, found {len(out_msgs)}")
    for exp, got in zip(expected, out_msgs):
        if original_text[exp.start:exp.end] != out_text[got.start:got.end]:
            problems.append(f"message {exp.index} changed byte-for-byte")
            break

    root = _ROOT_TAG.search(out_text).group(0)
    count = _COUNT_ATTR.search(root)
    if count and int(count.group(2)) != len(out_msgs):
        problems.append(f"root count={count.group(2)} but file has {len(out_msgs)} messages")

    try:  # whole-document well-formedness (after decoding the app's surrogate references)
        etree.fromstring(_decode_surrogates(out_text).encode("utf-8"))
    except etree.XMLSyntaxError as e:
        problems.append(f"output is not well-formed XML: {e}")
    return problems
