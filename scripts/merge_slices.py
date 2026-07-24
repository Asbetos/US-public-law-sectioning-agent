"""Merge N slice subagent responses for a volume into one response JSON, deduping
proposals and flagging conflicts. Usage: merge_slices.py <vol> <n_slices>"""
import json, sys
from pathlib import Path

SCRATCH = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/processed_output/scratch")


def _norm_title(t):
    return " ".join(str(t or "").lower().split())[:80]


def main(vol, n):
    slices = [f"subagent_response_{vol}_s{i}.json" for i in range(1, n + 1)]
    all_props, all_issues, notes, per = [], [], [], {}
    for s in slices:
        p = SCRATCH / s
        if not p.exists():
            print(f"!! missing {s}"); continue
        d = json.loads(p.read_text())
        per[s] = (len(d.get("proposals", [])), len(d.get("issues", [])))
        all_props += d.get("proposals", []); all_issues += d.get("issues", [])
        if d.get("notes"): notes.append(f"[{s}] {d['notes']}")

    print("per-slice (proposals, issues):")
    for s, v in per.items(): print(f"  {s}: {v}")

    seen, deduped = set(), []
    for pr in all_props:
        trig = pr.get("trigger", {}); corr = pr.get("correction", {})
        key = (str(trig.get("law_id_substring", "")), _norm_title(trig.get("title_substring", "")),
               str(corr.get("replace_with_law_id", "")))
        if key in seen: continue
        seen.add(key); deduped.append(pr)

    by_title = {}
    for pr in deduped:
        t = _norm_title(pr.get("trigger", {}).get("title_substring", ""))
        by_title.setdefault(t, set()).add(str(pr.get("correction", {}).get("replace_with_law_id", "")))
    title_conflicts = {t: v for t, v in by_title.items() if len(v) > 1}

    targets = {}
    for pr in deduped:
        tgt = str(pr.get("correction", {}).get("replace_with_law_id", ""))
        targets.setdefault(tgt, []).append(_norm_title(pr.get("trigger", {}).get("title_substring", "")))
    collisions = {t: sorted(set(v)) for t, v in targets.items() if len(set(v)) > 1}

    print(f"\nproposals: {len(all_props)} raw -> {len(deduped)} deduped | issues: {len(all_issues)}")
    print(f"title conflicts (same law -> different target): {len(title_conflicts)}")
    for t, v in title_conflicts.items(): print(f"   CONFLICT {t!r} -> {sorted(v)}")
    print(f"target collisions (different laws -> same number): {len(collisions)}")
    for t, v in collisions.items(): print(f"   COLLISION target={t} <- {v}")

    out = SCRATCH / f"subagent_response_{vol}.json"
    out.write_text(json.dumps({"proposals": deduped, "issues": all_issues,
                               "notes": " || ".join(notes)}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
