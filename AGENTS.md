# Maintainer schema — Embedded Security (Awesome KB)

This KB conforms to the **OpenShelf** standard (`openshelf: "0.1"`,
`profile: awesome`) — spec and schemas live in
[hexsecs/openkb](https://github.com/hexsecs/openkb); this file carries only
what is local to this KB. Read `kb.yaml` for the declared layout.
The maintenance **method** (deepening pipeline, evidence discipline,
concept mining, gates, traps) lives in the awesome-kb skill —
[hexsecs/awesome-kb-skill](https://github.com/hexsecs/awesome-kb-skill) —
not in this file; this file wins on local facts, the skill on method,
the spec on format.

## The canon rule

[hexsecs/awesome-embedded-security](https://github.com/hexsecs/awesome-embedded-security)
is canon (designated by the owner 2026-11-01). Ingest flows list → KB
only: a resource exists in this KB because it is on the list. Research
here may *propose* list additions, but never adds a page for an unlisted
resource. The list's own contribution rules decide what gets listed.

## Layout

- `wiki/<slug>.md` — entity pages, one per list entry (`type: entity`).
- `wiki/concepts/<slug>.md` — concept pages (`type: concept`),
  cross-linked synthesis over entities; listed in `index.md` directly.
- `wiki/index-<category>.md` — generated sub-index per list category
  (no frontmatter; do not edit by hand).
- `index.md` — the L1 index, generated from page frontmatter; it reads
  as a classic awesome list. Do not edit by hand.
- `tools/ingest.py` — the ingester (see `x-ingest` in `kb.yaml`).

## Local deltas from the automotive KB's ingester

- The source list groups categories as `###` headings under `##` parts
  (Software Tools / Hardware Tools / Further Learning and Training /
  Other Awesome Lists). An entry's category is its `###` heading, or the
  part title for entries listed directly under a part.
- List entries may carry one marker token between the link and the
  description (🗄️ archived, 💰 paid). The marker is list-side metadata:
  the ingester's grammar tolerates it, and it is not carried into pages.
  Page `status` is still verified from primary sources during deepening,
  never copied from the marker.

## Page contract (from the OpenShelf spec, restated for editors)

- `summary` ≤ 160 chars. The list's verbatim description lives in the
  body and in `list_summary`.
- `depth: stub | brief | full | deep` (SPEC §4.5): stubs are generated;
  `brief` is the shortest authored tier (a short orientation — who it is
  for, what you actually get, caveats — outbound link checked, status
  verified, no how-it-works section); `full` is the standard researched
  page; `deep` is the rare research-grade tier, on demand only.
- `created` is the date the page first entered the KB; set once by the
  ingester, never changes — distinct from `updated` and `last_checked`.
- `status` is verified from primary sources; `published` is for finished
  works (papers, talks, books), `unknown` only for living resources whose
  state is unverified.
