#!/usr/bin/env python3
"""Ingest the source awesome list into this KB, in OpenShelf format.

The list is canon (see AGENTS.md). This ingester parses its README with the
same entry grammar the list's own validator enforces — `* [name](url) - desc`
under `##` sections — and maintains this KB's OpenShelf awesome profile:

- `wiki/<slug>.md` — one entity page per list entry (frontmatter per the
  OpenShelf page schema; `summary` is capped at 160 chars, the list's
  verbatim description is kept in the body and in `list_summary`),
- `wiki/index-<category>.md` — one sub-index per list section, no
  frontmatter, generated from page frontmatter,
- `index.md` — the L1 index linking the sub-indexes; reads as the list.

Existing pages with an authored depth (`brief`, `full`, or `deep`)
keep their body; only provenance frontmatter is refreshed. Stub pages
are regenerated from the entry. Unmanaged frontmatter blocks on an existing page
(`related`, `tags`, a richer `sources`, …) are preserved verbatim, so
hand-written depth survives a sync. Concept pages under `wiki/concepts/`
are listed in the L1 index.

Entry identity is the normalised URL, with a slug fallback: if an entry's
URL moves but its name still slugifies to an existing page's stem, the page
is updated in place (a move is not a delisting). Pages whose entry leaves
the list entirely are tombstoned (`status: archived`, body note appended
once), never deleted, and stay listed in their sub-index so every page
remains reachable from the index.

A page is rewritten only when its own entry data changes (title, URL,
section, or list description). `last_checked` is a human/agent verification
stamp and is never moved by an ingest; `updated` and `source_commit`
advance only on pages actually rewritten. `created` is stamped from the
source commit date when a stub is first created and preserved verbatim
thereafter — it records when the page first entered the KB and never
changes (OpenShelf SPEC section 4.2). Deterministic and idempotent:
dates come from the source commit, never the wall clock; same source
commit in, byte-identical tree out.

Usage: python3 tools/ingest.py [--source ../awesome-automotive-security]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
ENTRY_RE = re.compile(r"^\* \[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)(?: \S+)? - (?P<desc>.+)$")
HEADING_RE = re.compile(r"^## (?P<title>.+)$")
SUBHEADING_RE = re.compile(r"^### (?P<title>.+)$")
SKIP_SECTIONS = {"Contents", "Contribute"}
SOURCE_ID = "awesome-embedded-security"
SOURCE_URL = "https://github.com/hexsecs/awesome-embedded-security"
KB_TITLE = "Embedded Security (Awesome KB)"
KB_DESC = ("Knowledge base for embedded security, ingested from the curated "
           "awesome list hexsecs/awesome-embedded-security.")


def normalise(url: str) -> str:
    """The list validator's identity rule: case, trailing slash, https ignored."""
    u = url.rstrip("/").lower()
    return u[len("https://"):] if u.startswith("https://") else u


def slugify(name: str, taken: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "entry"
    base, n = slug, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    taken.add(slug)
    return slug


def q(value: str) -> str:
    """A YAML-safe double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def short_summary(desc: str) -> str:
    """OpenShelf summary: <=160 chars, cut at a word boundary."""
    desc = desc.strip()
    if len(desc) <= 160:
        return desc
    cut = desc[:157].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "…"


def parse_list(readme: Path) -> list[dict]:
    # The embedded list groups its categories (###) under parts (##).
    # An entry's category is the latest ### heading, or the ## part title
    # itself for entries listed directly under a part.
    entries, part, section = [], None, None
    for line in readme.read_text(encoding="utf-8").splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            part = heading.group("title").strip()
            section = part
            continue
        sub = SUBHEADING_RE.match(line)
        if sub:
            section = sub.group("title").strip()
            continue
        match = ENTRY_RE.match(line)
        if match and section and part not in SKIP_SECTIONS \
                and section not in SKIP_SECTIONS:
            entries.append({"title": match.group("name"),
                            "url": match.group("url"),
                            "section": section,
                            "summary": match.group("desc")})
    return entries


MANAGED_KEYS = {"title", "summary", "type", "category", "url", "status",
                "last_checked", "created", "updated", "depth", "source_list",
                "source_commit", "list_summary"}


def frontmatter_blocks(text: str) -> list[tuple[str, list[str]]]:
    """Split a page's frontmatter into (key, raw lines) top-level blocks."""
    if not text.startswith("---\n"):
        return []
    end = text.find("\n---\n", 4)
    if end == -1:
        return []
    blocks: list[tuple[str, list[str]]] = []
    for line in text[4:end].splitlines():
        if line and not line.startswith((" ", "-", "\t")) and ": " in line or \
                line.endswith(":") and line[:-1].isidentifier():
            blocks.append((line.split(":", 1)[0].strip(), [line]))
        elif blocks:
            blocks[-1][1].append(line)
    return blocks


def extra_blocks(text: str) -> list[list[str]]:
    """Frontmatter blocks the ingester does not manage, kept verbatim."""
    return [lines for key, lines in frontmatter_blocks(text)
            if key not in MANAGED_KEYS]


def frontmatter(e: dict, status: str, depth: str, date: str, commit: str,
                extras: list[list[str]] | None = None,
                last_checked: str | None = None,
                created: str | None = None,
                updated: str | None = None) -> str:
    lines = ["---",
             f"title: {q(e['title'])}",
             f"summary: {q(short_summary(e['summary']))}",
             "type: entity",
             f"category: {q(e['section'])}",
             f"url: {q(e['url'])}",
             f"status: {status}",
             f"last_checked: {last_checked or date}",
             f"created: {created or date}",
             f"updated: {updated or date}",
             f"depth: {depth}",
             f"source_list: {SOURCE_ID}",
             f"source_commit: {commit}",
             f"list_summary: {q(e['summary'])}"]
    extras = extras or []
    for block in extras:
        lines.extend(block)
    if not any(block and block[0].startswith("sources:") for block in extras):
        lines += ["sources:",
                  f"  - url: {q(SOURCE_URL)}",
                  f"    retrieved: {date}"]
    lines.append("---")
    return "\n".join(lines) + "\n"


def stub_body(e: dict) -> str:
    return (f"\n{e['summary']}\n\n"
            f"- **Resource:** {e['url']}\n"
            f"- **List section:** {e['section']}\n"
            f"- **Source:** [{SOURCE_ID}]({SOURCE_URL}) — the list is canon;"
            f" this page is a generated stub (`depth: stub`). Depth is added"
            f" by PR (see AGENTS.md).\n")


def split_page(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fields = {}
    for line in text[4:end].splitlines():
        if ": " in line and not line.startswith(" "):
            key, raw = line.split(": ", 1)
            try:
                fields[key.strip()] = json.loads(raw)
            except json.JSONDecodeError:
                fields[key.strip()] = raw.strip('"')
    return fields, text[end + 5:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(ROOT.parent / SOURCE_ID),
                        help="checkout of the source list repo")
    args = parser.parse_args()
    source = Path(args.source)
    readme = source / "README.md"
    if not readme.exists():
        sys.exit(f"source README not found: {readme}")
    commit = subprocess.run(["git", "-C", str(source), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    date = subprocess.run(["git", "-C", str(source), "log", "-1", "--format=%cs", commit],
                          capture_output=True, text=True, check=True).stdout.strip()

    entries = parse_list(readme)
    WIKI.mkdir(exist_ok=True)

    existing: dict[str, Path] = {}
    by_stem: dict[str, Path] = {}
    for page in sorted(WIKI.rglob("*.md")):
        fields, _ = split_page(page.read_text(encoding="utf-8"))
        if "url" in fields:
            existing[normalise(str(fields["url"]))] = page
            by_stem[page.stem] = page

    taken = {p.stem for p in WIKI.glob("*.md")}
    entry_urls = {normalise(e["url"]) for e in entries}
    matched: set[Path] = set()
    by_section: dict[str, list[dict]] = {}
    created = updated = 0
    for e in entries:
        key = normalise(e["url"])
        page = existing.get(key)
        if page is None:
            # URL moved? An entry under a new URL keeps its page when the
            # name's slug matches a page whose URL is no longer listed.
            candidate = by_stem.get(slugify(e["title"], set()))
            if candidate is not None and candidate not in matched:
                cfields, _ = split_page(candidate.read_text(encoding="utf-8"))
                if normalise(str(cfields.get("url", ""))) not in entry_urls:
                    page = candidate
        if page is None:
            slug = slugify(e["title"], taken)
            page = WIKI / f"{slug}.md"
            # Finished works (the Research Papers category) are complete
            # at listing time: their status is `published` (OpenShelf
            # SPEC §9.2), not the unverified default for living resources.
            new_status = ("published" if e["section"] == "Research Papers"
                          else "unknown")
            page.write_text(frontmatter(e, new_status, "stub", date, commit)
                            + stub_body(e), encoding="utf-8")
            created += 1
        else:
            old_text = page.read_text(encoding="utf-8")
            fields, body = split_page(old_text)
            changed = (
                str(fields.get("title", "")) != e["title"]
                or normalise(str(fields.get("url", ""))) != key
                or str(fields.get("category", "")) != e["section"]
                or str(fields.get("list_summary", "")) != e["summary"])
            if changed:
                depth = str(fields.get("depth", "stub"))
                status = str(fields.get("status", "unknown"))
                new_text = frontmatter(
                    e, status, depth, date, commit, extra_blocks(old_text),
                    last_checked=str(fields.get("last_checked", "")) or None,
                    created=str(fields.get("created", "")) or None,
                    updated=date) + (
                    body if depth != "stub" else stub_body(e))
                page.write_text(new_text, encoding="utf-8")
                updated += 1
        matched.add(page)
        by_section.setdefault(e["section"], []).append(
            {"slug": page.stem, "title": e["title"],
             "summary": short_summary(e["summary"])})

    tombstoned = 0
    for page in sorted(set(existing.values()) - matched):
        if page.stem.startswith("index-"):
            continue
        text = page.read_text(encoding="utf-8")
        fields, _ = split_page(text)
        if fields.get("status") != "archived":
            text = re.sub(r"^status: .*$", "status: archived", text,
                          count=1, flags=re.M)
            if "Delisted from the source list" not in text:
                text += (f"\n> Delisted from the source list as of {commit}."
                         f" Tombstoned, not deleted (see AGENTS.md).\n")
            page.write_text(text, encoding="utf-8")
            tombstoned += 1
        # Tombstoned pages stay listed in their sub-index (marked), so
        # every page in wiki/ remains reachable from the index.
        category = str(fields.get("category", ""))
        if category:
            by_section.setdefault(category, []).append(
                {"slug": page.stem,
                 "title": f"{fields.get('title', page.stem)} (delisted)",
                 "summary": short_summary(
                     str(fields.get("list_summary", "")))})

    # Sub-indexes (no frontmatter — OpenShelf detects them as sub-indexes).
    by_section_order = list(by_section.keys())
    catslug = {}
    for section in by_section_order:
        cs = slugify(section, set())
        catslug[section] = cs
        lines = [f"# {section}", ""]
        for item in by_section[section]:
            lines.append(f"- [{item['title']}]({item['slug']}.md) — {item['summary']}")
        lines.append("")
        (WIKI / f"index-{cs}.md").write_text("\n".join(lines), encoding="utf-8")

    # L1 index.
    lines = [f"# {KB_TITLE}", "", KB_DESC,
             "Generated from page frontmatter by tools/ingest.py;"
             " do not edit by hand.", "", "## Categories", ""]
    for section in by_section_order:
        n = len(by_section[section])
        lines.append(f"- [{section}](wiki/index-{catslug[section]}.md)"
                     f" — {n} entr{'y' if n == 1 else 'ies'}")

    # Concept pages (hand-written synthesis) are listed directly in the L1.
    concepts_dir = WIKI / "concepts"
    concepts = []
    if concepts_dir.is_dir():
        for page in sorted(concepts_dir.glob("*.md")):
            fields, _ = split_page(page.read_text(encoding="utf-8"))
            if "title" in fields and "summary" in fields:
                concepts.append((str(fields["title"]), page.stem,
                                 str(fields["summary"])))
    if concepts:
        lines += ["", "## Concepts", ""]
        for title, slug, summary in concepts:
            lines.append(f"- [{title}](wiki/concepts/{slug}.md) — {summary}")
    lines.append("")
    (ROOT / "index.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"ingest: {len(entries)} entries from {SOURCE_ID}@{commit} "
          f"— {created} created, {updated} updated, {tombstoned} tombstoned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
