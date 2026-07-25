"""Rule-based pre-filter — surface candidates for the cv-correct subagent.

Two independent detection passes:

1. **Law-number range anomalies** — walks `<pLaw>` elements in XML order
   (NOT sorted by LawNumber — sorting would hide which duplicate is the wrong
   one). Numeric law identifier is extracted from `<citableAs>` (modern) or
   `<sidenote>` (legacy). Anomalies surface as `duplicate`, `out_of_place`
   (when a number breaks the local +1 trend with continuous neighbours),
   `gap` (when the next number isn't `previous + 1`), `suspect_endpoint`
   (first or last number is far off and the inner sequence is continuous),
   or `unparseable`.

2. **UniqueKey duplicates** — pandas `.duplicated("UniqueKey")` on the
   enriched DataFrame. Each duplicate group is one candidate; the agent
   inspects the rows + their XML to decide if it's a fixable extractor bug
   or a data-quality issue the publisher's suffix logic should handle.

For every candidate we also attach `tag_path` (ancestor chain) and a line
range from `lxml` so the GPO log entries can cite exact line numbers.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from lxml import etree


# ---------- XML walking ----------

# Vol > 63: citableAs has "Public Law CONG-N" — capture N (after the dash).
_MODERN_CITABLE_AS_RE = re.compile(
    r"Public\s+Law\s+\d+\s*[-–—]\s*(\d+)", re.IGNORECASE
)
# Vol <= 63: sidenote has bracketed "Public Law N" or "Pub. No. N" — capture N.
_LEGACY_PUBLIC_LAW_RE = re.compile(r"\bPublic\s+Law\s+(\d+)", re.IGNORECASE)
_LEGACY_PUB_NO_RE = re.compile(
    r"[Pp]ub[l]?i[c]?[e]?\s*,?\.?\s*No\.?\s*(\d+)"
)
_VOL_FROM_FILENAME = re.compile(r"STATUTE-(\d+)\.xml$", re.IGNORECASE)


def _vol_from_xml_path(xml_path: Path) -> int | None:
    m = _VOL_FROM_FILENAME.search(str(xml_path))
    return int(m.group(1)) if m else None


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _tag_path_to(elem) -> str:
    """Return a multi-line ancestor chain ending at ``elem``, e.g.
    `<statutesAtLarge>\\n <main>\\n  <pLaw>`."""
    chain: list[str] = []
    cur = elem
    while cur is not None:
        chain.append(_strip_ns(cur.tag))
        cur = cur.getparent()
    chain.reverse()
    return "\n".join(" " * i + f"<{chain[i]}>" for i in range(len(chain)))


def _last_sourceline(elem) -> int | None:
    """Walk the subtree; return the largest known sourceline."""
    candidates: list[int] = []
    for descendant in elem.iter():
        line = getattr(descendant, "sourceline", None)
        if isinstance(line, int):
            candidates.append(line)
    return max(candidates) if candidates else None


def _extract_canonical(plaw_elem, ns: dict, vol: int) -> tuple[str, int | None]:
    """Mirror the main extractor's law-id logic.

    Returns ``(canonical_law_id, public_law_number_int)``. For vol > 63 we use
    the public-law number after the dash in ``<citableAs>``; for vol ≤ 63 we
    use a regex over ``<sidenote>``. ``public_law_number_int`` is the integer
    used for sequence/anomaly detection (NOT the Stat-citation page number).
    """
    def _text(xpath: str) -> str:
        el = plaw_elem.find(xpath, ns) if ns else plaw_elem.find(xpath.replace("uslm:", ""))
        if el is None:
            return ""
        return "".join(el.itertext()).strip()

    if vol > 64:
        citable = _text(".//uslm:citableAs")
        m = _MODERN_CITABLE_AS_RE.search(citable)
        if m:
            return citable, int(m.group(1))
        # Fallback to <docNumber> when citableAs is empty or non-standard
        doc_no = _text(".//uslm:docNumber")
        m = re.search(r"\d+", doc_no)
        if m:
            congress = _text(".//uslm:congress")
            canonical = f"Public Law {congress}-{m.group(0)}" if congress else f"Public Law {m.group(0)}"
            return canonical, int(m.group(0))
        return citable, None

    sidenote = _text(".//uslm:sidenote")
    m = _LEGACY_PUBLIC_LAW_RE.search(sidenote) or _LEGACY_PUB_NO_RE.search(sidenote)
    if m:
        num = int(m.group(1))
        congress = _text(".//uslm:congress")
        canonical = f"{congress}-{num}" if congress else str(num)
        return canonical, num
    return sidenote[:120], None


def walk_plaws(xml_path: Path, vol: int) -> list[dict[str, Any]]:
    """Walk `<pLaw>` elements in document order; one dict per pLaw.

    Each dict has: ``xml_index``, ``citable_as`` (raw — for GPO log),
    ``sidenote`` (raw, truncated), ``canonical_law_id`` (extractor-shape, e.g.
    "Public Law 106-171" or "79-294"), ``law_number`` (integer used for
    anomaly sequencing), ``is_public``, ``congress_session``, ``official_title``,
    ``sourceline``, ``line_end``, ``tag_path``, ``xml_excerpt``.
    """
    tree = etree.parse(str(xml_path))
    root = tree.getroot()
    ns_uri = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""
    ns = {"uslm": ns_uri} if ns_uri else {}

    plaws = root.findall(".//uslm:pLaw", ns) if ns else root.findall(".//pLaw")
    out: list[dict[str, Any]] = []
    for i, p in enumerate(plaws):
        def _text(xpath: str) -> str:
            el = p.find(xpath, ns) if ns else p.find(xpath.replace("uslm:", ""))
            if el is None:
                return ""
            return "".join(el.itertext()).strip()

        # A pLaw typically has TWO <citableAs> elements:
        #   1. "Public Law 87–292"       — public-law citation
        #   2. "75 Stat. 611"            — Statutes-at-Large page citation
        # The GPO log targets human reviewers who work from printed Statutes
        # volumes, so the page citation is what they expect in the "Citable
        # As" column. Capture both; subagent + record_proposals decide use.
        citable_as_all = p.findall(".//uslm:citableAs", ns) if ns else p.findall(".//citableAs")
        citable_as_texts = ["".join(el.itertext()).strip() for el in citable_as_all]
        citable_as_pl = next((t for t in citable_as_texts if "Public Law" in t or "Pub. L." in t), "")
        citable_as_stat = next((t for t in citable_as_texts if " Stat. " in t), "")
        sidenote = _text(".//uslm:sidenote")
        official_title = _text(".//uslm:officialTitle")
        congress = _text(".//uslm:congress")
        session = _text(".//uslm:session")
        pp_raw = _text(".//uslm:publicPrivate")
        canonical, law_num = _extract_canonical(p, ns, vol)

        excerpt_full = etree.tostring(p, encoding="unicode")
        excerpt = excerpt_full[:3000] + ("..." if len(excerpt_full) > 3000 else "")

        out.append({
            "xml_index": i,
            "citable_as": citable_as_pl or (citable_as_texts[0] if citable_as_texts else ""),
            "statutes_citation": citable_as_stat,
            "sidenote": sidenote[:300],
            "canonical_law_id": canonical,
            "law_number": law_num,
            "is_public": pp_raw.lower() == "public",
            "congress_session": f"{congress}-{session}" if congress or session else "",
            "congress_human": (
                f"{congress} Session {session}" if congress and session
                else (congress or session or "")
            ),
            "official_title": official_title[:200],
            "sourceline": getattr(p, "sourceline", None),
            "line_end": _last_sourceline(p),
            "tag_path": _tag_path_to(p),
            "xml_excerpt": excerpt,
        })
    return out


# ---------- detection ----------

def _neighbours(seq: list[dict], i: int, window: int = 3) -> list[dict]:
    """Light-weight neighbour snapshots (no XML excerpt) for context."""
    lo, hi = max(0, i - window), min(len(seq), i + window + 1)
    return [
        {
            "offset": k - i,
            "xml_index": seq[k]["xml_index"],
            "citable_as": seq[k]["citable_as"],
            "canonical_law_id": seq[k]["canonical_law_id"],
            "law_number": seq[k]["law_number"],
        }
        for k in range(lo, hi)
        if k != i
    ]


def detect_law_number_anomalies(sequence: list[dict], *, public_only: bool = True) -> list[dict]:
    """Walk the XML-order sequence; flag suspect entries.

    The output preserves XML order. The agent does the final judgement —
    this only surfaces *suspects*.
    """
    seq = [s for s in sequence if (s.get("is_public") if public_only else True)]
    if len(seq) < 2:
        return []

    anomalies: list[dict] = []
    first_seen: dict[int, int] = {}

    # Pass 1: unparseable + duplicates (preserves "the later occurrence is the suspect")
    for i, item in enumerate(seq):
        ln = item["law_number"]
        if ln is None:
            anomalies.append({
                "kind": "unparseable",
                "suspect_index_in_seq": i,
                "xml_index": item["xml_index"],
                "suspect_citable_as": item["citable_as"],
                "suspect_canonical_law_id": item["canonical_law_id"],
                "suspect_law_number": None,
                "description": (
                    f"Could not parse a law number from citableAs={item['citable_as']!r}; "
                    f"sidenote={item['sidenote']!r}."
                ),
                "neighbours": _neighbours(seq, i),
                "line_range": [item["sourceline"], item.get("line_end")],
                "tag_path": item["tag_path"],
                "congress_session": item.get("congress_session", ""),
                "official_title": item.get("official_title", ""),
            })
            continue
        if ln in first_seen:
            first_idx = first_seen[ln]
            anomalies.append({
                "kind": "duplicate",
                "suspect_index_in_seq": i,
                "xml_index": item["xml_index"],
                "suspect_citable_as": item["citable_as"],
                "suspect_canonical_law_id": item["canonical_law_id"],
                "suspect_law_number": ln,
                "duplicate_of_xml_index": seq[first_idx]["xml_index"],
                "description": (
                    f"Law number {ln} already appeared at xml_index {seq[first_idx]['xml_index']}. "
                    "The later occurrence is the typical suspect."
                ),
                "neighbours": _neighbours(seq, i),
                "first_occurrence_neighbours": _neighbours(seq, first_idx),
                "line_range": [item["sourceline"], item.get("line_end")],
                "tag_path": item["tag_path"],
                "congress_session": item.get("congress_session", ""),
                "official_title": item.get("official_title", ""),
            })
        else:
            first_seen[ln] = i

    # Pass 2: sequence breaks — only over first occurrences (avoid double-counting dupes)
    first_indices = sorted(first_seen.values())
    for j, i in enumerate(first_indices):
        item = seq[i]
        ln = item["law_number"]
        prev_ln = seq[first_indices[j - 1]]["law_number"] if j > 0 else None
        next_ln = seq[first_indices[j + 1]]["law_number"] if j < len(first_indices) - 1 else None
        next_next_ln = seq[first_indices[j + 2]]["law_number"] if j + 2 < len(first_indices) else None
        prev_prev_ln = seq[first_indices[j - 2]]["law_number"] if j - 2 >= 0 else None

        kind: str | None = None
        description: str | None = None

        if j == 0:
            # First in order: validate against next two
            if next_ln is not None and next_ln - ln != 1:
                if next_next_ln is not None and next_next_ln - next_ln == 1:
                    kind = "suspect_endpoint"
                    description = (
                        f"First law in XML order is {ln}; next two are {next_ln} and "
                        f"{next_next_ln} (continuous). {ln} looks like the misnumbered endpoint."
                    )
        elif j == len(first_indices) - 1:
            # Last in order: validate against prev two
            if prev_ln is not None and ln - prev_ln != 1:
                if prev_prev_ln is not None and prev_ln - prev_prev_ln == 1:
                    kind = "suspect_endpoint"
                    description = (
                        f"Last law in XML order is {ln}; prev two are {prev_prev_ln} and "
                        f"{prev_ln} (continuous). {ln} looks like the misnumbered endpoint."
                    )
        else:
            # Middle: classify based on step pattern
            step_back = ln - prev_ln if prev_ln is not None else None
            step_fwd = next_ln - ln if next_ln is not None else None
            if step_back != 1 or step_fwd != 1:
                if (prev_ln is not None and next_ln is not None
                        and next_ln - prev_ln == 2):
                    kind = "out_of_place"
                    description = (
                        f"Law {ln} sits between {prev_ln} and {next_ln} in XML order; "
                        f"expected {prev_ln + 1} there — {ln} looks misnumbered."
                    )
                elif step_back is not None and step_back != 1:
                    kind = "gap"
                    description = (
                        f"Sequence gap before {ln} (XML order): previous was {prev_ln}, "
                        f"expected {prev_ln + 1}, got {ln}. May be a real veto/skip "
                        f"or a misnumbering — examine the XML."
                    )

        if kind is not None:
            anomalies.append({
                "kind": kind,
                "suspect_index_in_seq": i,
                "xml_index": item["xml_index"],
                "suspect_citable_as": item["citable_as"],
                "suspect_statutes_citation": item.get("statutes_citation", ""),
                "suspect_canonical_law_id": item["canonical_law_id"],
                "suspect_law_number": ln,
                "description": description,
                "neighbours": _neighbours(seq, i),
                "line_range": [item["sourceline"], item.get("line_end")],
                "tag_path": item["tag_path"],
                "congress_session": item.get("congress_session", ""),
                "congress_human": item.get("congress_human", ""),
                "official_title": item.get("official_title", ""),
            })

    return anomalies


def detect_unique_key_duplicates(
    df: pd.DataFrame,
    plaw_lookup: dict[str, dict] | None = None,
) -> list[dict]:
    """Group rows by duplicated UniqueKey; return one candidate per group.

    ``plaw_lookup`` maps the DataFrame's ``LawIdentifier`` string to the
    matching pLaw metadata dict from :func:`walk_plaws` — used to attach the
    Statutes-at-Large citation, congress label, and line range so each
    duplicate group can produce a complete GPO log row even when the
    subagent only inspects the dup candidate.
    """
    if df.empty or "UniqueKey" not in df.columns:
        return []
    mask = df.duplicated("UniqueKey", keep=False) & df["UniqueKey"].notna()
    if not mask.any():
        return []
    dups = df.loc[mask]
    out: list[dict] = []
    plaw_lookup = plaw_lookup or {}
    for key, group in dups.groupby("UniqueKey"):
        rows = json.loads(group.to_json(orient="records"))
        if len(rows) > 6:
            extra = len(rows) - 6
            rows = rows[:6] + [{"_truncated": f"+{extra} more rows omitted"}]
        law_ids = sorted(group["LawIdentifier"].dropna().astype(str).unique().tolist())
        # Per-law GPO context: each affected LawIdentifier becomes its own row
        # in the GPO log even when the proposal consolidates the root cause.
        per_law_context = []
        for lid in law_ids:
            meta = plaw_lookup.get(lid, {})
            per_law_context.append({
                "law_identifier": lid,
                "citable_as": meta.get("citable_as", lid),
                "statutes_citation": meta.get("statutes_citation", ""),
                "congress_human": meta.get("congress_human", ""),
                "line_range": [meta.get("sourceline"), meta.get("line_end")],
                "tag_path": meta.get("tag_path", ""),
            })
        out.append({
            "unique_key": key,
            "occurrence_count": int(group.shape[0]),
            "rows": rows,
            "law_identifiers": law_ids,
            "per_law_context": per_law_context,
        })
    return out


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--enriched", required=True, type=Path)
    parser.add_argument("--validation-report", required=True, type=Path)
    parser.add_argument("--active", required=True, type=Path)
    parser.add_argument("--pending", required=True, type=Path)
    parser.add_argument("--xml", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--include-private", action="store_true",
                        help="By default the law-number scan considers only public laws.")
    parser.add_argument("--max-law-anomalies", type=int, default=80,
                        help="Cap on law-number anomalies emitted (most volumes produce 0).")
    parser.add_argument("--max-unique-key-groups", type=int, default=80)
    args = parser.parse_args(argv)

    if not args.enriched.exists():
        print(f"Enriched parquet not found: {args.enriched}", file=sys.stderr)
        return 2
    if not args.xml.exists():
        print(f"Source XML not found: {args.xml}", file=sys.stderr)
        return 2

    df = pd.read_parquet(args.enriched)
    validation_report = (
        json.loads(args.validation_report.read_text())
        if args.validation_report.exists() else {}
    )

    vol = _vol_from_xml_path(args.xml)
    if vol is None:
        print(f"Could not derive volume number from {args.xml.name!r}", file=sys.stderr)
        return 2
    plaw_sequence = walk_plaws(args.xml, vol)
    law_anomalies = detect_law_number_anomalies(
        plaw_sequence, public_only=not args.include_private
    )
    if len(law_anomalies) > args.max_law_anomalies:
        law_anomalies = law_anomalies[: args.max_law_anomalies]

    plaw_lookup = {item["citable_as"]: item for item in plaw_sequence if item.get("citable_as")}
    uk_dups = detect_unique_key_duplicates(df, plaw_lookup=plaw_lookup)
    if len(uk_dups) > args.max_unique_key_groups:
        uk_dups = uk_dups[: args.max_unique_key_groups]

    # XML excerpts indexed by xml_index of the suspects (and their first-occurrence pair for dups).
    needed_indices: set[int] = set()
    for a in law_anomalies:
        needed_indices.add(a["xml_index"])
        if "duplicate_of_xml_index" in a:
            needed_indices.add(a["duplicate_of_xml_index"])
    xml_excerpts_by_xml_index = {
        str(item["xml_index"]): item["xml_excerpt"]
        for item in plaw_sequence
        if item["xml_index"] in needed_indices
    }

    payload = {
        "volume_from_enriched_path": args.enriched.stem,
        "total_rows": int(len(df)),
        "total_plaws_in_xml": len(plaw_sequence),
        "law_number_anomalies": law_anomalies,
        "unique_key_duplicates": uk_dups,
        "xml_excerpts_by_xml_index": xml_excerpts_by_xml_index,
        "validation_report_status": validation_report.get("status"),
        "validation_warnings": validation_report.get("warnings", []),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    print(
        f"Wrote {args.out}: {len(law_anomalies)} law-number anomalies, "
        f"{len(uk_dups)} UniqueKey duplicate groups, "
        f"{len(plaw_sequence)} pLaws walked."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
