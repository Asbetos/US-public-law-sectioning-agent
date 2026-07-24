# Citizen Voice pipeline — legacy-volume issues (≤ vol 63)

**Date:** 2026-06-30
**Found during:** `cv-correct` batch run on vols 44–64 (20 vols processed; vol 60 already published/skipped).
**Run outcome:** 7 published (55,57,59,61,62,63,64), 11 `validate_failed`, 2 `parse_failed`. All findings below are verified against the code and the actual run output.

Each issue is written to be filed/reported independently. File references use `path:line`.

---

## Issue 1 — Malformed-law-id repair pass misfires on legacy volumes, publishing chapter numbers as the law id

- **Severity:** High (data correctness — affects the primary identifier for *every* public law in legacy volumes)
- **Affected:** all legacy volumes (≤63). Confirmed on the 6 legacy volumes published this run (55,57,59,61,62,63); also applies to the ~30 legacy volumes published in batch2 and to vol 60.
- **Symptom:** the published `LawIdentifier` for a legacy law is `Public Law {congress}–{chapter}` instead of the public-law number. Example: a 1941 Navy/Marine-Corps law publishes as **`Public Law 77–320`** (320 = its chapter), when its public-law number is 188.
- **Root cause:** `_repair_malformed_law_identifiers` (`parser/uslm_parser.py:735-802`). The raw legacy extractor emits ids in the prefix-less form `{congress}-{n}` (e.g. `77-5`), which do **not** match `_CANONICAL_PUBLIC_LAW_ID = re.compile(r"Public Law \d+[-–—]\d+")` (`parser/uslm_parser.py:36`). The pass therefore treats them as "malformed" and rebuilds the id from `<docNumber>` + `<congress>` as `Public Law {congress}-{docNumber}`. For **modern** volumes (>63) `<docNumber>` *is* the public-law number (correct); for **legacy** volumes `<docNumber>` is the **chapter** number (wrong). The pass docstring shows it was designed for modern vols 105 and 108.
- **Evidence:** vol 55 suspect pLaw — XML `<docNumber>=320`, `<congress>=77`, `<sidenote>="…[Public Law 5]"`; published `LawIdentifier = 'Public Law 77–320'` (dash = U+2013).
- **Suggested fix:** gate `_repair_malformed_law_identifiers` to `vol > 63`. For legacy volumes, derive the id from the sidenote public-law number, emitted in canonical `Public Law {congress}–{N}` form.

---

## Issue 2 — Raw legacy extractor crashes the whole volume on a pLaw with missing `<publicPrivate>`

- **Severity:** High (whole-volume failure — no output produced)
- **Affected:** vols **44, 48** (status `parse_failed`); will hit any legacy volume containing such a pLaw.
- **Symptom:** `AttributeError: 'NoneType' object has no attribute 'text'`; the entire volume aborts with no Excel written.
- **Root cause:** `legacy/Extract_Sections_Divisions_From_XML.py:148-149` —
  `lawtype = plaw.find(".//uslm:publicPrivate", ns); lawtype = lawtype.text`
  with no guard for a missing/empty `<publicPrivate>` element.
- **Evidence:** vol 44 traceback terminates at `Extract_Sections_Divisions_From_XML.py:149`.
- **Suggested fix:** null-guard `<publicPrivate>` (skip the pLaw or fall back to a default classification) so a single malformed pLaw cannot abort the whole volume.

---

## Issue 3 — Legacy sidenote regex misses many pLaws → empty `LawIdentifier` → `validate_failed`

- **Severity:** High (whole-volume failure — no output for 11 volumes)
- **Affected:** vols **45, 46, 47, 49, 50, 51, 52, 53, 54, 56, 58** (status `validate_failed`). Blank-id counts include vol 54 = 206, vol 52 = 141, vol 53 = 139, vol 51 = 3, vol 56 = 2, vol 58 = 1.
- **Symptom:** validator hard-fails with `LawIdentifier values without recognizable pattern: N (sample: '')` — i.e. many pLaws produced an **empty** law id.
- **Root cause:** the legacy branch (`legacy/Extract_Sections_Divisions_From_XML.py:177-208`) only extracts a number when `<sidenote>` matches `\bPublic Law\s+\d+…` or a `Pub. No.` variant; otherwise `law_identifiers` stays `''`. The repair pass (Issue 1) does not rescue these. The validator requires `\d+[-–—]\d+` (`validation/validator.py:89-93`), so any empty id fails the volume.
- **Evidence:** vol 52 — 141 pLaws with blank `LawIdentifier`.
- **Suggested fix:** robust legacy law-number extraction with a deterministic fallback (document-order sequence + chapter offset) so no public pLaw yields an empty id.

---

## Issue 4 — cv-correct prefilter derives law ids in a different namespace than the published data, so corrections never apply

- **Severity:** High (the correction feature is effectively inert for legacy volumes)
- **Affected:** every legacy volume reviewed by cv-correct (this run: 55,57,59,61,62,63).
- **Symptom:** with `--include-pending`, the publisher mutated **~0 law-id cells** despite 12 proposed law-id corrections across the batch (vol 62 mutated 1 cell, attributable to a pre-existing active rule).
- **Root cause:** `prefilter.py` (`_extract_canonical` / `walk_plaws`, `~/.claude/skills/cv-correct/prefilter.py:80-115`) re-derives the law id as `{congress}-{sidenote_PL_number}` (e.g. `77-5`), while the published `LawIdentifier` is `Public Law {congress}–{chapter}` (Issue 1). The publisher matches `trigger.law_id_substring` as a substring of `LawIdentifier` (`apply_corrections_and_publish.py:37-51`). `77-5` — and even the corrected `77-188` — is not a substring of `Public Law 77–320`. Verified: even after reformatting triggers to the en-dash form, **0 of 12** match, because the *number itself* differs (PL number vs chapter).
- **Suggested fix:** have the prefilter surface the actual enriched `LawIdentifier`/`LawTitle` (it already loads the enriched parquet) so the subagent builds triggers in the published namespace. Largely resolved once Issue 1 aligns the namespaces.

---

## Issue 5 — cv-correct `system_prompt.md` instructs a trigger format that cannot match the data

- **Severity:** Medium (compounds Issue 4; yields unusable proposals even after the namespace is fixed)
- **Affected:** the cv-correct skill (all volumes).
- **Symptom:** subagents emit `law_id_substring` like `80-622` (hyphen, no `Public Law` prefix); the data uses `Public Law 80–622` (en-dash U+2013, prefixed). The matcher does an exact substring check with no dash/prefix normalization → no match.
- **Root cause:** `~/.claude/skills/cv-correct/system_prompt.md` instructs the "canonical `{congress}-{number}`" form and every few-shot example uses the hyphen/no-prefix form. The working **active** corrections actually use `Public Law NN–MM` (en-dash) — e.g. `Public Law 88–181`.
- **Suggested fix:** update `system_prompt.md` so triggers use the verbatim published `LawIdentifier` form, and/or add dash+prefix normalization in the matcher (`apply_corrections_and_publish.py`).

---

## Minor / observability

- **Manifest `corrections_applied` is misleading.** `run_manifest.json` records `corrections_applied(active=57, pending=12)` for each published volume — these are *registry sizes considered*, not cells changed. Actual mutations were ~0 (Issues 4–5). Consider recording the mutation count instead/as well.
- **"Distinct LawIdentifier count != public pLaw count" warnings** (e.g. vol 59 diff −1) are downstream symptoms of law-id collapse — e.g. vol 59's `Public Law 160` and `160-A` joint resolution both reduce to `79-160` because the legacy regex drops the alphabetic suffix.

---

## Summary table

| # | Issue | Severity | Affected volumes |
|---|---|---|---|
| 1 | Repair pass publishes chapter # as law id (legacy) | High | all ≤63 |
| 2 | Crash on missing `<publicPrivate>` | High | 44, 48 |
| 3 | Empty `LawIdentifier` → validate_failed | High | 45,46,47,49,50,51,52,53,54,56,58 |
| 4 | cv-correct triggers don't match published namespace | High | 55,57,59,61,62,63 |
| 5 | `system_prompt.md` teaches wrong trigger format | Medium | cv-correct (all) |
