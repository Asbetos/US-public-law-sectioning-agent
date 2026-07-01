# Design: Legacy law-identity resolver module (Statutes vols ≤ 63)

**Date:** 2026-06-30
**Status:** Approved design — pending implementation plan
**Scope:** `citizen_voice` data-preprocessing-pipeline

---

## 1. Background

Running the `cv-correct` pipeline over Statutes-at-Large volumes 44–64 surfaced three
defects, all in the **law-identity derivation** for legacy volumes (≤ 63). See
`LEGACY_VOLUMES_ISSUES_2026-06-30.md` for the full issue report. The relevant three:

- **Issue 1 — chapter number published as the law id.** The post-extraction repair pass
  `_repair_malformed_law_identifiers` (`parser/uslm_parser.py:735-802`) treats the raw
  legacy extractor's prefix-less `{congress}-{n}` ids as "malformed" (they don't match
  `_CANONICAL_PUBLIC_LAW_ID`, `parser/uslm_parser.py:36`) and rebuilds them from
  `<docNumber>` + `<congress>`. For modern volumes (>63) `<docNumber>` *is* the public-law
  number (correct); for legacy volumes it is the **chapter** number (wrong). The pass was
  designed for modern vols 105/108.
- **Issue 2 — crash on missing `<publicPrivate>`.** `legacy/Extract_Sections_Divisions_From_XML.py:148-149`
  does `lawtype = plaw.find(...); lawtype = lawtype.text` with no null guard →
  `AttributeError` aborts the whole volume (vols 44, 48 → `parse_failed`).
- **Issue 3 — empty `LawIdentifier` → `validate_failed`.** The legacy sidenote regex
  (`legacy/Extract_Sections_Divisions_From_XML.py:177-208`) misses many pLaws, leaving
  `LawIdentifier` empty; the validator (`validation/validator.py:89-93`) hard-fails any id
  not matching `\d+[-–—]\d+` (vols 45,46,47,49,50,51,52,53,54,56,58; up to 206 blanks in vol 54).

## 2. Goal

A dedicated, independently-testable module that resolves legacy pLaw **identity** so that:
the pipeline never crashes on a malformed pLaw, no public pLaw yields an empty id, and the
published `LawIdentifier` is the **public-law number** (not the chapter).

## 3. Fixed decisions (from brainstorming)

1. **Identifier semantics:** legacy `LawIdentifier` = the per-Congress **public-law number**
   from `<sidenote>` (OCR-repaired only when blank), matching modern (>63) semantics.
2. **Module scope:** **law-identity only** (is_public, public-law number, null-safety).
   The existing section/division walking is reused unchanged.
3. **Output format:** **identical** to the current build — same 26 columns, same string
   formats. `LawIdentifier` keeps the exact shape `Public Law {congress}–{N}` (en-dash
   U+2013, "Public Law" prefix); only the *value* `{N}` changes (PL number, not chapter).
4. **Reconstruction strategy: Approach A** — extract the sidenote PL number **verbatim**
   (even if OCR-wrong); reconstruct **only** when the sidenote is blank/unparseable.
   Residual OCR errors / misnumberings flow to `cv-correct` for human-approved fixes.
   No silent overrides of parseable sidenotes.

## 4. Architecture & integration

**New module:** `legacy/legacy_law_identity.py`. One public entry point:

```python
resolve_legacy_law_identities(plaws, vol, ns) -> dict[int, LawIdentity]
#   LawIdentity = {"is_public": bool, "law_identifier": str | None}
#   law_identifier is the BARE form "{congress}-{N}" (publisher canonicalizes it)
```

It walks all `<pLaw>` elements of a legacy volume once and returns a per-pLaw identity map.
It owns the null-safe `<publicPrivate>` read (Issue 2) and PL-number resolution (Issues 1, 3).
It does **not** touch section/division walking, titles, dates, or string formatting.

**Three surgical integration edits:**

1. **`legacy/Extract_Sections_Divisions_From_XML.py`** — for `vol ≤ 63`, replace the inline
   sidenote-regex block (lines 177-208) with a lookup into the resolver's map (computed once
   at the top of the volume walk); make the shared `<publicPrivate>` read (lines 148-149)
   null-safe. The `vol > 63` modern branch is untouched.
2. **`parser/uslm_parser.py`** — gate `_repair_malformed_law_identifiers` to `vol > 63`
   (Issue 1 fix). Other post-passes (container recovery, null-num, sibling-level/appropriations)
   remain enabled for all volumes — they are orthogonal to law-id.
3. **Publisher / schema — no change.** `pipeline/publisher.py:94-154`
   (`_normalize_one_law_id` / `_normalize_law_identifier_column`) already rewrites any id to
   canonical `Public Law {congress}–{number}` (en-dash), accepting bare `79-600` →
   `Public Law 79–600`. This guarantees byte-identical column formats.

**Data flow:**

```
raw extractor (legacy branch)
   └─ resolve_legacy_law_identities(plaws, vol, ns)      ← NEW: PL number, null-safe
        → LawIdentifier = "{congress}-{N}"                (bare; same shape as today)
   → recovery + null-num + sibling passes                (unchanged)
   → _repair_malformed_law_identifiers  [SKIPPED for ≤63] ← Issue 1 fix
   → validator: "{congress}-{N}" matches \d+–\d+           (passes; Issue 3 fixed)
   → publisher._normalize_one_law_id → "Public Law {congress}–{N}"  (identical format)
```

## 5. Resolver algorithm (Approach A)

Two deterministic passes over the volume's pLaws **in document order**.

**Pass 1 — classify + read sidenotes (no judgment calls):**
- **is_public** — read `<publicPrivate>` null-safely: present → `text.lower() == "public"`;
  missing/empty → infer from sidenote (`Public Law` ⇒ public, `Private Law` ⇒ private);
  if neither, default **public**. Private pLaws are excluded from the map.
- **sidenote PL number** — apply the existing regexes (`\bPublic Law\s+(\d+)`, `Pub. No.`
  variant); record `pl_raw` (int) or `None` — taken **verbatim** (OCR-wrong kept). Record
  `chapter = <docNumber>`.

**Pass 2 — fill only the blanks (deterministic monotonic continuation):**
Walk public pLaws in order, tracking `last_resolved`:
- `pl_raw` present → `resolved = pl_raw`; `last_resolved = pl_raw`.
- `pl_raw is None` → `resolved = last_resolved + 1`; `last_resolved = resolved`.
- **Leading blanks** (no `last_resolved` yet) → back-fill from the first downstream anchor:
  `resolved = first_anchor_pl − (#public pLaws between)`.
- **Chapter cross-check (advisory only):** compute the local `chapter − pl` offset from
  nearby anchors; if a filled value's implied offset deviates, **log** it as low-confidence.
  Never override (that is `cv-correct`'s responsibility).

Each public pLaw: `law_identifier = f"{congress}-{resolved}"`.

**Worked example (vol 55):** the Navy/Marine-Corps law has sidenote `[Public Law 5]` →
`pl_raw=5` → published `Public Law 77–5` (kept verbatim; cv-correct later proposes `77–188`).
A neighboring pLaw with a blank sidenote between `77–187` and `77–189` → filled `77–188`.
No crash, no blank, correct namespace.

## 6. Error handling & edge cases

| Case | Handling |
|---|---|
| `<publicPrivate>` missing/empty (Issue 2) | Infer from sidenote; default public. Never dereferences `None`. |
| Blank/garbage sidenote (Issue 3) | Deterministic fill (`last_resolved + 1` / leading back-fill). Never empty. |
| Private pLaw | Excluded from map; extractor `continue`s — eliminates the current suspicious `break` (`Extract_...py:206-208`) that aborts the remaining walk. |
| `<congress>` missing on a pLaw | Use the volume's modal congress (shared across pLaws) so the id is never `"-N"`. |
| Two pLaws resolve to the same number | Not deduped here — surfaces as the validator's existing *warning* and/or a cv-correct anomaly. |
| **No** parseable sidenote anywhere in the volume (no anchors) | Fall back to document-order ordinals (1, 2, 3, …) as PL numbers so the volume still validates; log a volume-level low-confidence warning. (Implausible in practice — the `validate_failed` volumes had partial, not total, blanks.) |
| Low-confidence flag surfacing | A logger warning only — **no new column** (preserves identical output format). Structured prioritization for cv-correct is a future enhancement (Approach C), not part of this module. |

## 7. Testing

**Unit tests** on `resolve_legacy_law_identities` with synthetic pLaw fixtures: verbatim
sidenote; missing `<publicPrivate>` (no crash + inferred); blank → `+1` fill; leading-blank
back-fill; private-law exclusion; missing-congress fallback; chapter cross-check logs but
does not override.

**Regression tests** on the real 20 volumes (44–64, excl. 60) from the 2026-06-30 run:
- **44, 48** → parse to completion (no `AttributeError`; status `ready_for_publish`).
- **45,46,47,49,50,51,52,53,54,56,58** → zero blank `LawIdentifier`s; validator passes.
- **55,57,59,61,62,63** → row counts & all columns unchanged in shape; `LawIdentifier` now
  in PL-number namespace (spot-check known laws); repair pass confirmed not firing.
- **Modern regression (e.g. 64, 105, 108)** → identical published data (all rows, all
  columns, all values) vs current build (module gated to ≤63; 105/108 must still be repaired
  by the still-enabled pass). Compare DataFrame contents, not filenames (which carry timestamps).
- **Format-snapshot test** → every column's dtype/string-shape matches the current build for
  a legacy volume; only `LawIdentifier` *values* change.

## 8. Rollout & out of scope

- **Rollout is a separate decision.** The fix changes `LawIdentifier` *values* for all ≤63
  volumes, including the ~30 legacy volumes + vol 60 already published (hard-frozen).
  Re-publishing them requires `--force-republish` + explicit operator approval. Building the
  module touches nothing frozen.
- **Out of scope for this module:**
  - **cv-correct Issue 5 (dash/prefix format).** The parser fix aligns the *namespace*, but
    the prefilter emits a hyphen (`77-5`) while the published id uses an en-dash
    (`Public Law 77–5`), so cv-correct corrections still won't match until Issue 5 is fixed
    (normalize dashes in the matcher, or emit the published form). The parser fix alone does
    not fully restore cv-correct.
  - **The `-A` alphabetic-suffix collision** (vol 59's `160` vs `160-A`) — left to cv-correct.
  - **Modern (>63) behavior** — unchanged by design.

## 9. References

- Issue report: `LEGACY_VOLUMES_ISSUES_2026-06-30.md`
- Raw legacy extractor: `legacy/Extract_Sections_Divisions_From_XML.py:148-220`
- Repair pass + wrapper: `parser/uslm_parser.py:735-802`, `:805-872`, `:36`
- Validator rule: `validation/validator.py:89-93`
- Publisher normalizer: `pipeline/publisher.py:94-154`
- Prefilter (cv-correct): `~/.claude/skills/cv-correct/prefilter.py:80-115`
- Publisher matcher (cv-correct): `apply_corrections_and_publish.py:37-51`
