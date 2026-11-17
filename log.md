# Log

## [2026-11-01] init | Embedded Security (Awesome KB) created

Knowledge base created at the owner's direction ("Make the awesome-kb
for my awesome embedded security list"), following the network's
established pattern (hexsecs/awesome-kb-automotive-security): OpenShelf
`awesome` profile, the source list hexsecs/awesome-embedded-security as
canon, an ingester adapted from the automotive KB's (two-level
`##`/`###` category grammar; tolerance for the list's marker tokens),
standalone GitHub Pages render via the registry builder pinned at an
exact commit, and registry registration. Initial ingest brings every
list entry in as a stub page; deepening follows in slices.

## [2026-11-02] adopt | OpenShelf spec 1.4 adoption: uid backfill + restamp

Minted the KB `uid` and a `uid` for all 253 pages with `openshelf uid`
(the spec 1.4 adoption path, SPEC §4.1), restamped kb.yaml
`openshelf: "0.1"` → `"1.4"`, and taught tools/ingest.py the uid
lifecycle: mint on stub creation, preserve verbatim on rewrites.
Gates: ingest ×2 idempotent (0/0/0), `openshelf lint --strict` clean;
wiki diff is exactly one added `uid:` line per page.

## [2026-11-16] tooling | link_mine.py: mined `related:` cross-links for every entity page

The ingester creates each page as an island (no `related:`), and until
now links appeared only where a deepening pass wrote them by hand —
in this KB, nowhere: all 285 entity pages carried zero cross-links.
tools/link_mine.py is the missing machine pass: it scores page pairs
from title/summary token overlap (IDF-weighted), category, resource
org, and title mentions, and writes the strongest relations as a
reciprocal `related:` block (an author-owned field the ingester
preserves verbatim, verified: ingest reports 0/0/0 after mining).
First run: 284 pages linked, average 5.4 related per page, one page
(embeddedsecurity-io, a list-of-lists) with no qualifying relation.
The daily ingest sync now runs the miner after ingest so new stubs
land linked and neighbours gain the reciprocal link in the same
commit. Concept candidates are mined separately by
tools/concept_scan.py and filed as gated issues, never auto-built.
