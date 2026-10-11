"""Write-check-retry pipeline.

For every overlay:
  1. The fact-checker recomputes the overlay's facts from raw events. If they
     do not match, the overlay is held back (never aired).
  2. The writer drafts a caption for the chosen mode.
  3. The fact-checker vets the draft. If it fails, the reasons go back to the
     writer for another try (up to `max_attempts`).
  4. If every draft fails, the detector's own template text is used, but only
     if it also passes the check. Otherwise the overlay is held back.

Each result keeps a `check_log` of every draft and why it was accepted or
rejected, so a producer (or a judge) can see the self-correction happen.

Usage:
    python -m agents.pipeline --events data/match_001_events.jsonl --mode analyst
    python -m agents.pipeline --events data/match_001_events.jsonl --fault 0.4
    python -m agents.pipeline --events data/match_001_events.jsonl --writer llm   (needs LLM_* variables)
"""
from __future__ import annotations

import argparse
import json
import os

from engine.moments import detect_all
from engine.replayer import load_events

from .factcheck import FactChecker
from .writers import LocalWriter, OpenAICompatibleWriter


def run(overlays: list[dict], events: list[dict], teams: dict, writer,
        mode: str = "casual", max_attempts: int = 3, lang: str = "en"):
    """Return (results, summary). Results keep the original overlay fields.

    `lang` is "en", "pcm" (Nigerian Pidgin) or "yo" (Yoruba). If no draft in that
    language passes the check, the detector's English text is used instead and
    `text_language` says so, rather than airing an unchecked translation.
    """
    checker = FactChecker(events, teams)
    results = []
    summary = {"total": 0, "first_try": 0, "fixed_by_retry": 0, "fallback": 0, "held_back": 0}

    for o in overlays:
        summary["total"] += 1
        r = dict(o)
        r.update(base_text=o["text"], mode=mode, language=lang, text_language=lang, writer=writer.name,
             attempts=0, check_log=[])

        grounding = checker.check_facts(o)
        if grounding:
            r.update(verified=False, held_back=True)
            r["check_log"].append({"attempt": 0, "stage": "facts", "ok": False, "issues": grounding})
            summary["held_back"] += 1
            results.append(r)
            continue

        final, feedback = None, None
        for attempt in range(1, max_attempts + 1):
            draft = (writer.write(o, mode, feedback) if lang == "en"
                     else writer.write(o, mode, feedback, lang))
            issues = checker.check_text(o, draft, lang)
            r["check_log"].append({"attempt": attempt, "stage": "text", "text": draft,
                                   "ok": not issues, "issues": issues})
            r["attempts"] = attempt
            if not issues:
                final = draft
                summary["first_try" if attempt == 1 else "fixed_by_retry"] += 1
                break
            feedback = issues

        if final is None and not checker.check_text(o, o["text"]):
            final = o["text"]
            r["fallback"] = True
            r["text_language"] = "en"
            summary["fallback"] += 1

        if final is None:
            r.update(verified=False, held_back=True)
            summary["held_back"] += 1
        else:
            r.update(verified=True, text=final)
        results.append(r)
    return results, summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", default="data/match_001_events.jsonl")
    ap.add_argument("--mode", choices=("analyst", "casual"), default="casual")
    ap.add_argument("--writer", choices=("local", "llm"), default="local")
    ap.add_argument("--fault", type=float, default=0.0,
                    help="local writer only: chance (0-1) of a deliberate mistake on the first draft")
    ap.add_argument("--lang", choices=("en", "pcm", "yo"), default="en",
                    help="caption language: en, pcm (Nigerian Pidgin) or yo (Yoruba)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", help="output JSON path")
    args = ap.parse_args()

    events = load_events(args.events)
    meta_path = args.events.replace("_events.jsonl", "_meta.json")
    with open(meta_path, encoding="utf-8") as f:
        teams = json.load(f)["teams"]
    overlays = detect_all(events, teams)
    writer = (OpenAICompatibleWriter.from_env(teams) if args.writer == "llm"
              else LocalWriter(teams, args.fault, args.seed))

    results, summary = run(overlays, events, teams, writer, args.mode, lang=args.lang)

    for r in results:
        at = r["at"]
        mark = "OK  " if r["verified"] else "HELD"
        print(f'{at["minute"]:>2}\':{at["second"]:02d} {mark} {r["headline"]:<12} {r["text"]}')
        for entry in r["check_log"]:
            if not entry["ok"]:
                reasons = "; ".join(entry["issues"])
                tail = "" if r["verified"] else " (held back)"
                print(f'        caught on attempt {entry["attempt"]}: {reasons}{tail}')
                if entry.get("text"):
                    print(f'        rejected draft: {entry["text"]}')

    out = args.out or args.events.replace("_events.jsonl", f"_overlays_{args.mode}{'' if args.lang == 'en' else '_' + args.lang}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n{summary['total']} overlays -> {out}")
    print(f"accepted first try: {summary['first_try']}, fixed after a rejection: "
          f"{summary['fixed_by_retry']}, fell back to template: {summary['fallback']}, "
          f"held back: {summary['held_back']}")


if __name__ == "__main__":
    main()
