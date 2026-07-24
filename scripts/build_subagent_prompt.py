"""Build a filled cv-correct subagent prompt file per volume from system_prompt.md."""
import json, sys
from pathlib import Path

SKILL = Path("/home/G39248410/.claude/skills/cv-correct")
PIPE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline")
OUT = PIPE / "processed_output"
SCRATCH = OUT / "scratch"

REASONING = (
    "\n\nThink very hard about each anomaly before deciding. For every law-number "
    "anomaly, examine the suspect's official title, the neighbouring laws' citations, "
    "and the XML structure. For every UniqueKey-duplicate group, compare the rows "
    "column-by-column AND inspect the source XML to classify as extractor-fixable vs. "
    "XML-data-quality. Do not propose corrections you are not confident about — leaving "
    "a row un-corrected is always preferable to a wrong correction that mutates a "
    "published Excel. ultrathink."
)

def _trim(obj, limit=200):
    """Recursively truncate long strings so the dedup context stays small.
    record_proposals.py dedups on the full (type,trigger,correction) anyway;
    the subagent only needs enough to recognise an already-proposed fix."""
    if isinstance(obj, str):
        return obj if len(obj) <= limit else obj[:limit] + "…"
    if isinstance(obj, list):
        return [_trim(x, limit) for x in obj]
    if isinstance(obj, dict):
        return {k: _trim(v, limit) for k, v in obj.items()}
    return obj

def _dedup_summary(path: Path):
    """Compact one-entry-per-line summary (type + trigger id/title) so the
    subagent can recognise an already-proposed fix without the multi-hundred-KB
    evidence blobs. record_proposals.py remains the authoritative dedup gate."""
    d = json.loads(path.read_text())
    arr = d if isinstance(d, list) else d.get("corrections", d.get("proposals", []))
    out = []
    for x in arr if isinstance(arr, list) else []:
        trig = x.get("trigger", {}) if isinstance(x, dict) else {}
        corr = x.get("correction", {}) if isinstance(x, dict) else {}
        out.append({
            "type": x.get("type"),
            "trigger_law_id": (str(trig.get("law_id_substring", ""))[:80]),
            "trigger_title": (str(trig.get("title_substring", trig.get("heading_substring", "")))[:120]),
            "correction": (str(corr.get("replace_with_law_id", corr.get("replace_with_section_number", corr.get("description", ""))))[:80]),
        })
    return out

def build(vol: int, start=None, end=None, excerpt_limit=None, suffix="") -> Path:
    tmpl = (SKILL / "system_prompt.md").read_text()
    cand = json.loads((SCRATCH / f"candidates_{vol}.json").read_text())
    active = _dedup_summary(OUT / "active_corrections.json")
    pending = _dedup_summary(OUT / "pending_corrections.json")
    valrep = json.loads((SCRATCH / f"validation_report_{vol}.json").read_text())

    anomalies = cand.get("law_number_anomalies", [])
    if start is not None:
        anomalies = anomalies[start:end]
    needed = set()
    for a in anomalies:
        needed.add(str(a.get("xml_index")))
        if "duplicate_of_xml_index" in a:
            needed.add(str(a.get("duplicate_of_xml_index")))
    xml_excerpts = {k: v for k, v in cand.get("xml_excerpts_by_xml_index", {}).items()
                    if not needed or k in needed}
    if excerpt_limit:
        xml_excerpts = {k: (v[:excerpt_limit] + "…" if len(v) > excerpt_limit else v)
                        for k, v in xml_excerpts.items()}
    xml_text = "\n\n".join(f"[xml_index {k}]\n{v}" for k, v in xml_excerpts.items())

    filled = (tmpl
        .replace("{VOLUME_NUMBER}", str(vol))
        .replace("{ACTIVE_CORRECTIONS_JSON}", json.dumps(active, indent=2))
        .replace("{PENDING_CORRECTIONS_JSON}", json.dumps(pending, indent=2))
        .replace("{LAW_NUMBER_ANOMALIES_JSON}", json.dumps(anomalies, indent=2))
        .replace("{UNIQUE_KEY_DUPLICATES_JSON}", json.dumps(cand.get("unique_key_duplicates", []), indent=2))
        .replace("{XML_EXCERPTS}", xml_text)
        .replace("{VALIDATION_REPORT_JSON}", json.dumps(valrep, indent=2))
    ) + REASONING

    out = SCRATCH / f"subagent_prompt_{vol}{suffix}.txt"
    out.write_text(filled)
    return out

if __name__ == "__main__":
    # usage: build_subagent_prompt.py <vol> [start end suffix excerpt_limit]
    if len(sys.argv) >= 4:
        vol = int(sys.argv[1]); start = int(sys.argv[2]); end = int(sys.argv[3])
        suffix = sys.argv[4] if len(sys.argv) > 4 else ""
        lim = int(sys.argv[5]) if len(sys.argv) > 5 else None
        p = build(vol, start, end, excerpt_limit=lim, suffix=suffix)
        print(f"vol {vol}[{start}:{end}]: {p} ({len(p.read_text())} chars)")
    else:
        for v in sys.argv[1:]:
            p = build(int(v))
            print(f"vol {v}: {p} ({len(p.read_text())} chars)")
