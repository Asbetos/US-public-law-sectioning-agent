"""Shared pytest config: put pipeline root and the legacy Code/ on sys.path."""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PIPELINE_ROOT = _HERE.parent           # data-preprocessing-pipeline/
_CODE_DIR = _PIPELINE_ROOT.parent       # /home/G39248410/citizen_voice/Code/

for p in (str(_PIPELINE_ROOT), str(_CODE_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
