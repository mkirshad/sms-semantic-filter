"""Command-line entry point.

    python -m sms_filter scan   backup.xml --topic topic.json --report report.csv
    python -m sms_filter apply  backup.xml --report report.csv --out cleaned.xml
    python -m sms_filter verify backup.xml cleaned.xml --report report.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time

from . import xmlio


def _chronological(messages):
    return sorted(messages, key=lambda m: (m.date, m.index))


def cmd_scan(a: argparse.Namespace) -> int:
    from . import classify

    _, messages = xmlio.read_backup(a.backup)
    topic = classify.load_topic(a.topic)
    msgs = _chronological(messages)
    print(f"Read {len(msgs)} messages from {a.backup}")

    t0 = time.time()
    scores = classify.embedding_scores(msgs, topic, a.window, a.embed_model)
    shortlist = [i for i, s in enumerate(scores) if s >= a.threshold]
    print(f"Stage 1 (embeddings): {len(shortlist)} candidates above {a.threshold} "
          f"in {time.time() - t0:.0f}s")

    verdicts = {}
    if a.no_llm:
        for i in shortlist:
            verdicts[i] = (True, scores[i], "embedding similarity only (--no-llm)")
    else:
        t0 = time.time()
        for n, i in enumerate(shortlist, 1):
            verdicts[i] = classify.llm_verdict(msgs, i, topic, a.window, a.llm_model, a.ollama)
            if n % 25 == 0 or n == len(shortlist):
                print(f"Stage 2 (local LLM): {n}/{len(shortlist)} reviewed")
        print(f"Stage 2 finished in {time.time() - t0:.0f}s")

    flagged = 0
    with open(a.report, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["remove", "file_index", "date", "direction", "contact", "text",
                    "similarity", "confidence", "reason"])
        for i, m in enumerate(msgs):
            if i not in verdicts:
                continue
            remove, conf, reason = verdicts[i]
            remove = remove and (a.no_llm or conf >= a.min_confidence)
            flagged += remove
            w.writerow(["yes" if remove else "no", m.index, m.readable_date, m.box,
                        m.contact, m.text, f"{scores[i]:.3f}", f"{conf:.2f}", reason])
    print(f"\n{flagged} messages flagged for removal. Review {a.report}: change 'remove' "
          f"to yes/no where needed, then run 'apply'. Nothing has been deleted yet.")
    return 0


def _read_flags(report: str) -> set[int]:
    with open(report, encoding="utf-8-sig", newline="") as f:
        return {int(r["file_index"]) for r in csv.DictReader(f)
                if r["remove"].strip().lower() in ("yes", "y", "true", "1")}


def cmd_apply(a: argparse.Namespace) -> int:
    if a.out == a.backup:
        print("Refusing to overwrite the original backup; choose a different --out file.")
        return 2
    text, messages = xmlio.read_backup(a.backup)
    remove = _read_flags(a.report)
    unknown = remove - {m.index for m in messages}
    if unknown:
        print(f"Report refers to messages not in this file: {sorted(unknown)[:10]}")
        return 2
    cleaned = xmlio.remove_messages(text, messages, remove)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(cleaned)
    problems = xmlio.verify(text, messages, a.out, remove)
    print(f"Removed {len(remove)} of {len(messages)} messages -> {a.out}")
    return _report_problems(problems)


def cmd_verify(a: argparse.Namespace) -> int:
    text, messages = xmlio.read_backup(a.backup)
    return _report_problems(xmlio.verify(text, messages, a.cleaned, _read_flags(a.report)))


def _report_problems(problems) -> int:
    if problems:
        print("VERIFICATION FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Verified: valid XML, count attribute correct, every kept message byte-identical to the original.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sms_filter", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="find messages about the topic and write a review report")
    s.add_argument("backup")
    s.add_argument("--topic", required=True, help="JSON file describing the topic")
    s.add_argument("--report", default="report.csv")
    s.add_argument("--window", type=int, default=3, help="neighbouring messages used as context")
    s.add_argument("--threshold", type=float, default=0.30, help="stage-1 similarity cut-off")
    s.add_argument("--min-confidence", type=float, default=0.6)
    s.add_argument("--embed-model", default="sentence-transformers/all-MiniLM-L6-v2")
    s.add_argument("--llm-model", default="llama3.1:8b")
    s.add_argument("--ollama", default="http://localhost:11434")
    s.add_argument("--no-llm", action="store_true", help="embeddings only (faster, less precise)")
    s.set_defaults(func=cmd_scan)

    ap = sub.add_parser("apply", help="write a cleaned copy using the reviewed report")
    ap.add_argument("backup")
    ap.add_argument("--report", default="report.csv")
    ap.add_argument("--out", required=True)
    ap.set_defaults(func=cmd_apply)

    v = sub.add_parser("verify", help="check a cleaned file against the original")
    v.add_argument("backup")
    v.add_argument("cleaned")
    v.add_argument("--report", default="report.csv")
    v.set_defaults(func=cmd_verify)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
