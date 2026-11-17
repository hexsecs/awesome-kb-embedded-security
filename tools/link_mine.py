#!/usr/bin/env python3
"""Mine cross-links for this KB: fill `related:` on entity pages.

The ingester (tools/ingest.py) creates each page as an island: it never
writes `related:`, and links otherwise appear only when a human or agent
deepens a page by hand. This tool is the missing machine pass. It scores
every pair of entity pages from the signals a stub actually carries —
title, list summary, category, resource URL — and writes the strongest
relations as a reciprocal `related:` block.

Signals (all deterministic; same corpus in, same links out):
- shared significant tokens in title+summary, weighted by inverse
  document frequency (rare tokens are the informative ones);
- a page's title mentioned in another page's summary (strong);
- same list category (weak boost);
- same resource host/org, e.g. the same GitHub organisation (medium).

`related:` is an author-owned field (the ingester preserves unmanaged
frontmatter blocks verbatim), so mined links survive ingest syncs. A
page whose block changes gets its `updated:` stamp moved to the run
date — a mined link set is a substantive change to a stub.

Modes:
- default: recompute every non-archived entity page's set from scratch
  (safe where pages are machine-generated stubs);
- --fill-only: touch only pages whose `related:` is empty (the mode
  for KBs with hand-curated pages), plus --reciprocate to complete
  one-way links that already exist;
- --dry-run: print the census and samples, write nothing.

Usage: python3 tools/link_mine.py [--dry-run] [--fill-only]
       [--reciprocate] [--date YYYY-MM-DD] [--max-related 8]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date as date_cls
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

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


def tokens(text: str) -> list[str]:
    out = []
    for tok in re.split(r"[^a-z0-9]+", text.lower()):
        if len(tok) >= 3 and tok not in STOPWORDS and not tok.isdigit():
            out.append(tok)
    return out


def split_page(text: str) -> tuple[dict, list[str], str]:
    """(scalar fields, frontmatter lines, body) — scalars best-effort."""
    if not text.startswith("---\n"):
        return {}, [], text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, [], text
    fm_lines = text[4:end].splitlines()
    fields: dict = {}
    for line in fm_lines:
        if ": " in line and not line.startswith((" ", "-")):
            key, raw = line.split(": ", 1)
            try:
                fields[key.strip()] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                fields[key.strip()] = raw.strip('"')
    return fields, fm_lines, text[end + 5:]


def parse_related(fm_lines: list[str]) -> list[str]:
    rels: list[str] = []
    for i, line in enumerate(fm_lines):
        if line.startswith("related:"):
            rest = line.split(":", 1)[1].strip()
            if rest.startswith("["):
                rels = [x.strip() for x in rest.strip("[]").split(",")
                        if x.strip()]
            else:
                for nxt in fm_lines[i + 1:]:
                    if nxt.startswith(("  - ", "- ")):
                        rels.append(nxt.split("- ", 1)[1].strip())
                    else:
                        break
            break
    return rels


def write_page(path: Path, fm_lines: list[str], body: str,
               related: list[str], run_date: str) -> None:
    """Replace/insert the related block; bump `updated:`; write the file."""
    out: list[str] = []
    i = 0
    block = ["related:"] + [f"  - {slug}" for slug in related]
    placed = False
    while i < len(fm_lines):
        line = fm_lines[i]
        if line.startswith("related:"):
            out.extend(block)
            placed = True
            i += 1
            # skip the old block's continuation lines
            while i < len(fm_lines) and fm_lines[i].startswith((" ", "-")):
                i += 1
            continue
        if line.startswith("updated:"):
            line = f"updated: {run_date}"
        out.append(line)
        if not placed and line.startswith("list_summary:"):
            out.extend(block)
            placed = True
        i += 1
    if not placed:
        out.extend(block)
    path.write_text("---\n" + "\n".join(out) + "\n---\n" + body,
                    encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fill-only", action="store_true",
                    help="only pages with an empty related: get a set")
    ap.add_argument("--reciprocate", action="store_true",
                    help="also complete one-way links that already exist")
    ap.add_argument("--date", default=None,
                    help="updated: stamp for changed pages (default: today ET)")
    ap.add_argument("--max-related", type=int, default=6)
    ap.add_argument("--threshold", type=float, default=3.0)
    args = ap.parse_args()
    run_date = args.date or str(
        date_cls.today() if False else
        __import__("datetime").datetime.now(ZoneInfo("America/Detroit")).date())

    pages: dict[str, dict] = {}
    for path in sorted(WIKI.glob("*.md")):
        if path.stem.startswith("index-"):
            continue
        text = path.read_text(encoding="utf-8")
        fields, fm_lines, body = split_page(text)
        if fields.get("type") != "entity" or "title" not in fields:
            continue
        if str(fields.get("status")) == "archived":
            continue
        pages[path.stem] = {
            "path": path, "fields": fields, "fm_lines": fm_lines,
            "body": body, "related": parse_related(fm_lines),
        }
    if not pages:
        print("link_mine: no entity pages found")
        return 0

    # Document frequencies over title+summary tokens.
    page_tokens: dict[str, Counter] = {}
    df: Counter = Counter()
    for slug, p in pages.items():
        f = p["fields"]
        toks = Counter(tokens(str(f.get("title", ""))) * 3
                       + tokens(str(f.get("summary", ""))) * 2)
        page_tokens[slug] = toks
        for tok in toks:
            df[tok] += 1
    n = len(pages)
    idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}

    def org_of(p: dict) -> str:
        # Only code-host orgs are a real signal (the same GitHub org
        # publishing two tools). A shared document host (usenix.org,
        # arxiv.org, youtube.com) says nothing about relatedness.
        url = str(p["fields"].get("url", ""))
        host = urlparse(url).netloc.lower()
        parts = [x for x in urlparse(url).path.split("/") if x]
        if host == "github.com" and parts:
            return f"github.com/{parts[0].lower()}"
        return ""

    # A category is evidence only when it is selective: a section
    # holding most of the corpus (e.g. Research Papers) boosts
    # everything and therefore nothing.
    cat_counts = Counter(str(p["fields"].get("category", ""))
                         for p in pages.values())

    slugs = sorted(pages)
    scores: dict[tuple[str, str], float] = {}
    for i, a in enumerate(slugs):
        ta = page_tokens[a]
        fa = pages[a]["fields"]
        title_a = str(fa.get("title", "")).lower()
        summ_a = str(fa.get("summary", "")).lower()
        for b in slugs[i + 1:]:
            tb = page_tokens[b]
            fb = pages[b]["fields"]
            shared = set(ta) & set(tb)
            s = sum(min(ta[t], tb[t]) * idf[t] for t in shared) / 3.0
            if fa.get("category") and fa.get("category") == fb.get("category") \
                    and cat_counts[str(fa.get("category"))] <= 0.20 * n:
                s += 1.0
            if org_of(pages[a]) and org_of(pages[a]) == org_of(pages[b]):
                s += 1.5
            title_b = str(fb.get("title", "")).lower()
            summ_b = str(fb.get("summary", "")).lower()
            distinctive_a = [t for t in tokens(title_a) if idf.get(t, 0) > 2.0]
            distinctive_b = [t for t in tokens(title_b) if idf.get(t, 0) > 2.0]
            if distinctive_b and all(t in summ_a for t in distinctive_b[:2]):
                s += 3.0
            if distinctive_a and all(t in summ_b for t in distinctive_a[:2]):
                s += 3.0
            if s >= args.threshold:
                scores[(a, b)] = s
                scores[(b, a)] = s

    # Directed top picks, then symmetrise by union, cap by pair score.
    directed: dict[str, list[str]] = defaultdict(list)
    for (a, b), s in scores.items():
        directed[a].append(b)
    for a in directed:
        directed[a].sort(key=lambda b: (-scores[(a, b)], b))
        directed[a] = directed[a][:5]
    final: dict[str, list[str]] = {}
    for a in slugs:
        cand = set(directed.get(a, []))
        cand |= {x for x in slugs if a in directed.get(x, [])}
        ranked = sorted(cand, key=lambda b: (-scores.get((a, b), 0.0), b))
        final[a] = ranked[:args.max_related]

    # Concept pages are never written by this tool, but their related
    # lists are sources for reciprocation: a concept that draws on an
    # entity should be linked back from that entity (house practice).
    concept_links: dict[str, list[str]] = {}
    cdir = WIKI / "concepts"
    if cdir.is_dir():
        for path in sorted(cdir.glob("*.md")):
            fields, fm_lines, _ = split_page(
                path.read_text(encoding="utf-8"))
            if "title" in fields:
                concept_links[path.stem] = parse_related(fm_lines)

    changed = filled = recip_added = 0
    samples: list[str] = []
    for slug in slugs:
        p = pages[slug]
        old = p["related"]
        # Who already links here, that this page does not link back to?
        incoming = {o for o in slugs if slug in pages[o]["related"]}
        incoming |= {c for c, rels in concept_links.items()
                     if slug in rels}
        if args.fill_only and old:
            # Author-owned set: preserve it verbatim and in order;
            # only append missing reciprocal links.
            new = list(old)
            if args.reciprocate:
                adds = sorted(incoming - set(new),
                              key=lambda b: (-scores.get((slug, b), 0.0), b))
                recip_added += len(adds)
                new = new + adds
        else:
            new = list(final[slug])
            if args.reciprocate:
                adds = sorted(incoming - set(new),
                              key=lambda b: (-scores.get((slug, b), 0.0), b))
                recip_added += len(adds)
                new = new + adds
            new = sorted(set(new),
                         key=lambda b: (-scores.get((slug, b), 0.0), b))
        if new != old:
            changed += 1
            if not old:
                filled += 1
            if len(samples) < 5:
                samples.append(f"  {slug}: {old} -> {new}")
            if not args.dry_run:
                write_page(p["path"], p["fm_lines"], p["body"], new, run_date)

    total_rel = sum(len(final[s]) for s in slugs)
    zero = sum(1 for s in slugs if not final[s])
    print(f"link_mine: {n} entity pages | mined sets avg "
          f"{total_rel / n:.2f} related/page, {zero} pages with none | "
          f"{'would change' if args.dry_run else 'changed'} {changed} pages "
          f"({filled} previously unlinked, {recip_added} reciprocal adds)")
    for line in samples:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
