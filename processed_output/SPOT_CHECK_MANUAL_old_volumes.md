# Spot-Check Manual: Verifying the Parsed Old-Volume Excel Sheets

## 1. Introduction

The old *Statutes at Large* volumes were parsed automatically by software that reads each printed volume and turns it into a spreadsheet — one row for every section of every law. This manual explains how to confirm the software did that correctly.

You will compare the published **Excel sheet** for a volume against the **printed volume (PDF)**. You are the human check that every law made it in, with the right number, title, date, and sections. You do **not** need any technical or XML files — just the Excel and the PDF.

## 2. Objective

For each volume, confirm that:

- every law in the printed volume appears in the Excel,
- each law has the correct number, title, type, and approval date, and
- each law's sections are split the same way they appear in print.

A volume has hundreds of laws, so you won't check every one. You'll check a representative **sample** and record anything that looks wrong.

**Volumes to check right now: 45 through 60.** (Volume 44 is still being finalised — skip it.)

## 3. What you need

1. The **Excel file** for the volume (from the delivered zip), e.g. `Volume-55/STATUTE-55_….xlsx`.
2. The **printed volume PDF** — the official scan from **govinfo.gov** (search "Statutes at Large Volume 55").
3. Open both side by side.

Two quick setup steps in the Excel:

- **Sort by the `Order` column** so the rows follow the same order as the printed book.
- To read one law at a time, **filter the `LawIdentifier` column** to a single value.

## 4. Two things to understand before you start

**(a) One law = several rows.** A law with 8 sections becomes about 8 rows that all share the same `LawIdentifier`. To view a whole law, filter to its `LawIdentifier`.

**(b) The law's number comes from the MARGIN, not the chapter.** Each printed law shows a **chapter number** in its header (e.g. `[CHAPTER 320.]`) and a **public-law number** in the margin (e.g. `[Public Law 5.]`). The Excel uses the **margin public-law number** — so this law is `Public Law 77–5`, *not* `77–320`. Always compare the Excel number to the **margin**, never to the chapter number. (Resolutions appear as `Public Resolution 77–5`.)

## 5. The steps

### Step 1 — Choose the laws to check (about 20–30 per volume)

Pick:

- the **first and last law of each session** in the volume,
- **every ~30th law** as you scroll through (to spread across the whole volume),
- **all Public Resolutions** (filter `LawIdentifier` for "Public Resolution"),
- **one or two appropriations acts** (the long ones with many headings),
- a few laws named in the volume's **GPO issue log** (`gpo_issue_log_vols45-60_….xlsx`).

### Step 2 — Open each chosen law in both places

Find the law in the PDF, and filter the Excel `LawIdentifier` to that same law.

### Step 3 — Run these checks, in order

1. **Is it there?** The law appears in the Excel (and nothing appears that isn't a real law in the PDF).
2. **Right number?** The `LawIdentifier` number matches the margin public-law / resolution number.
3. **Right type?** `LawType` matches — *Act*, *Joint Resolution*, or *Concurrent Resolution*.
4. **Right title?** `LawTitle` matches the printed title (small spacing differences are fine).
5. **Right date?** `approvedDate` (shown as `yyyy-mm-dd`) matches the "Approved, …" line at the end of the law.
6. **Sections match?** The `SectionNumber` values match the "SEC. 2.", "SEC. 3." … labels in print — same count, same numbers, in order, none missing, none doubled, none merged together.
7. **Text complete?** Read the first and last section's `Text`: it should begin and end where the printed section does — not cut off, and not spilling into the next section or law.
8. **(Appropriations acts only) Headings present?** The `DivisionHeadingLevel1/2/3` columns should show the department / bureau headings from the page.

If every check passes, mark the law **OK**. If anything is off, record it (Step 4).

### Do NOT flag these — they are correct on purpose

- The number being the **public-law number, not the chapter number**.
- Resolutions labeled **`Public Resolution …`**.
- Dates written as **`yyyy-mm-dd`**.
- A **blank section number on a law's first row** (the opening "Be it enacted…" paragraph is unnumbered in print).
- The `UniqueKey`, `Congress`, `Session`, and other internal columns — you don't compare these to the PDF.

## 6. Where and how to record issues

Record every issue in the **shared findings spreadsheet**: **[ paste the shared spreadsheet link here ]** — use one tab per volume.

Add **one row per issue**, with these columns:

| Column | What to put |
|---|---|
| **Volume** | e.g. `55` |
| **PDF page / cite** | The page number or Statutes cite, e.g. `55 Stat. 553` |
| **Chapter #** | From the law's header, e.g. `320` |
| **Margin #** | The public-law / resolution number in the margin, e.g. `188` |
| **Excel LawIdentifier** | e.g. `Public Law 77–5` |
| **UniqueKey** | The `UniqueKey` of the exact problem row — copy it from the Excel |
| **Issue type** | e.g. wrong number / missing law / merged sections / split section / duplicate / wrong type / truncated text |
| **What's wrong** | "The PDF says X, the Excel says Y" |
| **Severity** | **Blocking** (missing/duplicated law, merged/split sections, wrong number) or **Minor** (spacing, debatable heading) |

**Always copy the `UniqueKey`** of the problem row — that is how we locate the exact spot to fix.

**Example row:**

| Volume | PDF page / cite | Chapter # | Margin # | Excel LawIdentifier | UniqueKey | Issue type | What's wrong | Severity |
|---|---|---|---|---|---|---|---|---|
| 55 | 55 Stat. 553 | 320 | 188 | Public Law 77–5 | 055-077-1-005-000-000-000-000-000-S-000000000000001 | wrong number | Margin reads "Public Law 188" but the Excel shows 77–5 | Blocking |

Also keep a short **"checked & clean"** list of the law numbers you verified with no problems, so we know how much of the volume was covered.

When you finish a volume, send the spreadsheet to **[ pipeline owner ]**. Confirmed issues go into the correction queue.
