"""Shared pytest config: put the pipeline root and the in-repo legacy/ modules on sys.path."""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PIPELINE_ROOT = _HERE.parent             # data-preprocessing-pipeline/
_LEGACY_DIR = _PIPELINE_ROOT / "legacy"   # original extractor modules, vendored in this repo

for p in (str(_PIPELINE_ROOT), str(_LEGACY_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
