"""One-time helper — split a published legacy-volume Excel into one file per
(Congress, Session) and mark up to 600 random eligible rows per session for RA
coding.

This does NOT touch the main parser. It re-uses the pipeline's own selection
logic (`pipeline.segmenter.apply_selection_sampling`) so eligibility and the
`Selection`/`Order` marking match how the pipeline normally picks coding rows.

Every column and value is copied through unchanged EXCEPT the two marking
columns, which are re-generated fresh per session:
  - Selection : 1 on the sampled rows, 0 otherwise
  - Order     : 1..N (random) on the sampled rows, blank otherwise

Usage:
    python scripts/split_sessions_for_coding.py --volumes 45,46,47,48,49
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from pipeline.segmenter import apply_selection_sampling  # noqa: E402

DEFAULT_OUTPUT_DIR = _REPO / "processed_output"
SAMPLE_SIZE = 600


def _latest_published(vol: int, out_dir: Path) -> Path | None:
    fs = [x for x in sorted(glob.glob(str(out_dir / f"Volume-{vol}" / f"STATUTE-{vol}_*.xlsx")))
          if "_SME" not in x]
    return Path(fs[-1]) if fs else None


def _session_key(congress, session) -> tuple[str, str]:
    c = str(congress).strip()
    if c.endswith(".0"):
        c = c[:-2]
    if c in ("", "nan", "<NA>", "None"):
        c = "NA"
    s = str(session).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if s in ("", "nan", "<NA>", "None"):
        s = "NA"
    return c, s


def split_volume_by_session_and_mark(vol: int, out_dir: Path, dest_dir: Path,
                                     n: int = SAMPLE_SIZE) -> list[dict]:
    """Split volume ``vol``'s published Excel into one file per (Congress, Session),
    marking up to ``n`` eligible rows per session. Returns a per-session report."""
    src = _latest_published(vol, out_dir)
    if src is None:
        raise FileNotFoundError(f"No published Excel for volume {vol} under {out_dir}")
    df = pd.read_excel(src)
    columns = list(df.columns)  # exact 29-col order to preserve

    # Partition label per row: (Congress, Session) — except a codification bloc
    # (LawIdentifier "US Code <year>", e.g. vol 44's 1926 U.S. Code) is a huge,
    # distinct object nominally in one session, so it gets its OWN file rather
    # than swamping that session's sheet.
    def _partition(law_id, congress, session):
        lid = str(law_id).strip()
        if lid.startswith("US Code "):
            return lid.replace(" ", "-")           # "US-Code-1926"
        c, s = _session_key(congress, session)
        return f"{c}-{s}"

    df["_P"] = [_partition(l, c, s) for l, c, s in
                zip(df["LawIdentifier"], df["Congress"], df["Session"])]

    vol_dest = dest_dir / f"Volume-{vol}"
    vol_dest.mkdir(parents=True, exist_ok=True)

    report = []
    for label, part in df.groupby("_P", sort=True):
        part = part.drop(columns=["_P"]).copy()
        # fresh Selection/Order using the pipeline's eligibility + sampling
        marked = apply_selection_sampling(part, n=n)
        marked = marked[columns]  # keep exact column order
        out_path = vol_dest / f"STATUTE-{vol}_{label}.xlsx"
        marked.to_excel(out_path, index=False, engine="openpyxl")
        report.append({
            "volume": vol, "partition": label,
            "rows": len(marked), "marked": int((marked["Selection"] == 1).sum()),
            "file": str(out_path),
        })
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--volumes", required=True, help="comma list, e.g. 45,46,47,48,49")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    p.add_argument("--dest-dir", default=None,
                   help="where to write the split files (default: <output-dir>/session_coding_sheets)")
    p.add_argument("--sample-size", type=int, default=SAMPLE_SIZE)
    args = p.parse_args(argv)

    out_dir = Path(args.output_dir)
    dest_dir = Path(args.dest_dir) if args.dest_dir else out_dir / "session_coding_sheets"
    vols = [int(v) for v in args.volumes.split(",") if v.strip()]

    all_rows = []
    for vol in vols:
        rep = split_volume_by_session_and_mark(vol, out_dir, dest_dir, n=args.sample_size)
        for r in rep:
            all_rows.append(r)
            print(f"vol {r['volume']}  {r['partition']}: "
                  f"{r['rows']} rows, {r['marked']} marked -> {Path(r['file']).name}")
    print(f"\nWrote {len(all_rows)} session files to {dest_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
