# QA Report — Volume 44: missing Congress / Session / approvedDate cells

**Date:** 2026-07-22
**Volume:** 44 (69th Congress, 1925–1927)
**Published file audited:** `Volume-44/STATUTE-44_2026-07-22-13H-44M-45S.xlsx` (15,941 rows, 879 distinct LawIdentifiers)

---

## 1. Summary of findings

| Column | Missing cells | % of volume |
|---|---|---|
| Congress | 12,124 | 76.1% |
| Session | 12,124 | 76.1% |
| approvedDate | 12,124 | 76.1% |

**The missing cells are not scattered — they are one coherent bloc.** All 12,124
missing cells in each column belong to the **1926 U.S. Code codification**, and
the three columns go missing *together* on exactly the same rows.

**Every genuinely dated law is complete.** Outside the codification bloc there
are **zero** rows missing Congress, Session, or approvedDate — all 3,817 session
acts/resolutions and their sections have all three values populated.

So this is a single, well-defined data-completeness gap around one object (the
U.S. Code), not a systemic parsing failure.

---

## 2. What the bloc is

- The bloc is a **single `<pLaw>`** in the source XML (the first pLaw in
  `STATUTE-44.xml`), titled *"To consolidate, codify, and set forth the general
  and permanent laws of the United States in force December 7, 1925."* — i.e.
  the **U.S. Code, 1926 edition**, printed as Part 1 of Statutes-at-Large vol 44.
- It contains ~13,000 `<section>` elements (published as 12,029 Section rows +
  95 Division rows = 12,124 rows).
- In the source XML this pLaw has **empty `<docNumber>`, `<congress>`,
  `<session>`, `<approvedDate>`, and `<sidenote>`** — because a codification is
  not a single dated act, the source carries none of that metadata.

## 3. Root cause

1. The pipeline derives the `Congress` and `Session` columns **from the
   `approvedDate`** (via `Congress_Session_Dates.csv`). The codification has no
   `approvedDate` in the source, so the derivation returns null → `Congress` and
   `Session` are null, and the UniqueKey shows the "undated" sentinel `000-0`
   (e.g. `044-000-0-001-…`).
2. The `LawIdentifier` for the bloc is **`Public Law 69–1`**, produced by the
   legacy resolver's fallback: with an empty sidenote it used the volume's
   **modal congress (69)** and an **ordinal blank-fill (1)**. That value is
   plausible but inferred, not read from the source.

## 4. Related issue found during the audit (recommend fixing together)

The inferred label **`Public Law 69–1`** is **shared by three different things**:

| Rows | What it is | Dated? |
|---|---|---|
| 12,124 | the U.S. Code codification | no |
| 2 | the **real** Public Law 69‑1 (first act of the 69th Congress) | yes (has approvedDate) |
| (1) | Public Resolution 69‑1 (`Public Resolution 69-1`) | yes |

So the codification is **colliding on `Public Law 69–1` with the genuine first
act of the 69th Congress**. This is why the "69‑1" bucket looks mixed (mostly
undated, a few dated). It should be disambiguated so the real PL 69‑1 is not
conflated with the codification.

---

## 5. Rectification plan

The three missing columns are recoverable to different degrees. Recommended
resolution per column:

### 5a. `Congress` → **69** (high confidence, derive it)
The codification is unambiguously part of the 69th Congress's volume, and the
label already carries `69`. **Fill `Congress = 69`** for the bloc by falling back
to the LawIdentifier's congress when the date-derived value is null. This is a
small, safe extension of the existing "congress hint" logic and needs no
external data.

### 5b. `approvedDate` → **1926-06-30** *(decision required — domain value)*
The U.S. Code 1926 edition was prepared and set forth under the **Act of June 30,
1926 (44 Stat. 777, ch. 712)**. That authorizing date is *not in the source XML*,
so assigning it is a **convention decision**, not a parse. Options:
- **(A, recommended)** Set `approvedDate = 1926-06-30` for the whole bloc — a
  single, defensible, documented codification date, and it makes Session
  derivable.
- **(B)** Leave `approvedDate` blank — most literal to the source (a codification
  has no per-section enactment date), but leaves the column 76% empty.

### 5c. `Session` → **1** (follows from 5b)
June 30 1926 falls in the **69th Congress, 1st session** (Dec 7 1925 – Jul 3
1926). If option 5b-A is taken, Session derives to `1` automatically; if 5b-B is
taken, Session stays blank (or can be set to `1` directly).

### 5d. Disambiguate the label (fixes §4)
Relabel the codification so it no longer collides with the real Public Law 69‑1.
Two options:
- Give the codification a **distinct identifier** (e.g. `US Code 1926`), leaving
  `Public Law 69–1` for the genuine first act; **or**
- Keep the number but flag the codification via `LawType` / a marker column so
  downstream users can separate the ~12k codification rows from the 2 real
  PL 69‑1 rows.

---

## 6. Proposed implementation (once decisions in 5b & 5d are made)

1. Add a **targeted enrichment step for the codification bloc** (identified by
   the undated `Public Law 69–1` codification pLaw): set `Congress=69`,
   `Session=1`, `approvedDate=1926-06-30` (per decisions), and apply the chosen
   relabel/marker.
2. Regenerate + **force-republish vol 44**; the UniqueKey for the bloc changes
   from `044-000-0-…` to `044-069-1-…` (undated sentinel → real congress/session).
3. **Verify**: 0 missing cells in Congress/Session/approvedDate; the real
   Public Law 69‑1 (2 rows) separated from the codification; distinct-law count
   and all dated laws unchanged.
4. Add a regression test asserting the codification bloc carries
   `Congress=69 / Session=1 / approvedDate=1926-06-30` (or the chosen values).

**Scope note:** this is confined to vol 44 — no other volume has this bloc, and
no other volume has missing Congress/Session/approvedDate cells.

---

## 7. Decisions needed from the team

1. **approvedDate for the codification** — assign `1926-06-30` (recommended) or
   leave blank?
2. **Label** — give the codification a distinct id (`US Code 1926`), or keep
   `Public Law 69–1` + a marker column?

Once these are confirmed, the fix is a small, vol-44-only change + republish.
