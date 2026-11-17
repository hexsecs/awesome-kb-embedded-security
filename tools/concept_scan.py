#!/usr/bin/env python3
"""Scan the corpus for recurring themes: concept-page candidates.

Concept pages are this KB's original work, and they are mined, never
improvised (see the awesome-kb skill, references/concepts.md). This
scan is the periodic corpus-wide mining pass in tool form: it counts
significant phrases across every entity page's title and summary and
reports the themes that recur — with their page counts and example
pages — so a maintainer can evaluate candidates on evidence.

Generic corpus vocabulary (the KB's subject words, marketing verbs)
is filtered out; what survives is weighted toward multi-word phrases
and the technical acronyms (JTAG, BLE, TPM…) that name real themes.
Category names and existing concept pages are excluded — a candidate
that merely restates a list section is a label, not a concept.

The scan proposes; it never builds. A candidate becomes a concept
only through the evaluation in concepts.md (pattern across >=3
verified pages, a synthesis no entity page states, an explicit
overlap boundary, build readiness) and is filed as a discrete issue —
with a build gate naming the pages that must reach full depth first
when the evidence is still stub-level, as it is in a young KB.

Usage: python3 tools/concept_scan.py [--min-pages 6] [--top 25]
Prints a markdown candidate table to stdout.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with",
    "via", "using", "use", "used", "based", "from", "by", "at", "as",
    "is", "are", "be", "it", "its", "this", "that", "your", "you", "can",
    "into", "over", "under", "per", "etc", "one", "two", "new", "open",
    "source", "free", "tools", "tool", "library", "framework", "project",
    "support", "supports", "supported", "system", "systems", "software",
    "hardware", "embedded", "security", "analysis", "research",
}
# Corpus-generic vocabulary: true of the KB as a whole, or marketing
# filler — never a theme, however often it recurs.
GENERIC = {
    "firmware", "binary", "platform", "device", "devices", "covering",
    "providing", "supporting", "built", "across", "including", "includes",
    "allows", "allowing", "enables", "enabling", "designed", "featuring",
    "offers", "offering", "helps", "making", "makes", "comprehensive",
    "complete", "modern", "various", "multiple", "different", "powerful",
    "simple", "easy", "advanced", "automated", "automatic", "manual",
    "testing", "reverse", "engineering", "vulnerability", "attack",
    "execution", "protocol", "images", "image", "linux", "radio",
    "toolkit", "collection", "set", "suite", "environment", "interface",
    "interfaces", "implementation", "implementations", "development",
    "management", "generation", "discovery", " techniques", "techniques",
    "methods", "approach", "capabilities", "features", "real", "time",
    "real-time", "high", "low", "level", "levels", "written", "written in",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


def fields_of(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    fields = {}
    for line in text[4:end].splitlines():
        if ": " in line and not line.startswith((" ", "-")):
            key, raw = line.split(": ", 1)
            try:
                fields[key.strip()] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                fields[key.strip()] = raw.strip('"')
    return fields


def grams(text: str, acronyms: set[str]) -> set[str]:
    raw = TOKEN_RE.findall(text)
    toks = [t.lower() for t in raw
            if len(t) >= 3 and t.lower() not in STOPWORDS
            and not t.isdigit()]
    out: set[str] = set()
    for size in (1, 2, 3):
        for i in range(len(toks) - size + 1):
            g = toks[i:i + size]
            if any(t in STOPWORDS or t in GENERIC for t in g):
                continue
            phrase = " ".join(g)
            if size == 1:
                t = g[0]
                # A lone word is a theme only when it is a technical
                # term: an acronym in the source text, hyphenated, or
                # carrying a digit (stm32, risc-v, tpm2…).
                if not (t in acronyms or "-" in t
                        or any(c.isdigit() for c in t)):
                    continue
            out.add(phrase)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-pages", type=int, default=6)
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    pages: dict[str, dict] = {}
    categories: set[str] = set()
    for path in sorted(WIKI.glob("*.md")):
        if path.stem.startswith("index-"):
            continue
        f = fields_of(path.read_text(encoding="utf-8"))
        if f.get("type") != "entity" or "title" not in f:
            continue
        pages[path.stem] = f
        if f.get("category"):
            categories.add(str(f["category"]).lower())

    existing_concepts: set[str] = set()
    cdir = WIKI / "concepts"
    if cdir.is_dir():
        for path in sorted(cdir.glob("*.md")):
            existing_concepts.add(path.stem.replace("-", " "))

    # Acronyms: tokens the corpus itself capitalises (BLE, JTAG, TPM…).
    acronyms: set[str] = set()
    for f in pages.values():
        for tok in TOKEN_RE.findall(f"{f.get('title', '')} "
                                     f"{f.get('summary', '')}"):
            if len(tok) >= 3 and (tok.isupper() or tok[:1].isupper()
                                  and tok[1:].islower() is False):
                acronyms.add(tok.lower())

    hits: dict[str, set[str]] = defaultdict(set)
    for slug, f in pages.items():
        text = f"{f.get('title', '')} {f.get('summary', '')}"
        for g in grams(text, acronyms):
            hits[g].add(slug)

    n = len(pages)
    rows = []
    for phrase, slugs in hits.items():
        if len(slugs) < args.min_pages or len(slugs) > 0.20 * n:
            continue
        if phrase in categories or phrase in existing_concepts:
            continue
        words = phrase.split()
        score = len(slugs) * (1 + 0.4 * (len(words) - 1))
        if len(words) == 1 and phrase in acronyms:
            score *= 1.3
        rows.append((phrase, slugs, score))
    rows.sort(key=lambda r: (-r[2], r[0]))
    pruned: list[tuple[str, set[str], float]] = []
    for phrase, slugs, score in rows:
        if any(len(phrase) > len(p) and slugs <= s and phrase.startswith(p)
               for p, s, _ in pruned):
            continue
        pruned.append((phrase, slugs, score))
    pruned = pruned[:args.top]

    print(f"concept_scan: {n} entity pages, {len(existing_concepts)} "
          f"existing concepts, {len(pruned)} candidates with "
          f">= {args.min_pages} pages\n")
    print("| Candidate theme | Pages | Example pages |")
    print("|---|---|---|")
    for phrase, slugs, _ in pruned:
        ex = ", ".join(sorted(slugs)[:4])
        print(f"| {phrase} | {len(slugs)} | {ex} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
