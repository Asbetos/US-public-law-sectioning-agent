"""USLM parser facade.

The actual extractor lives in ``Extract_Sections_Divisions_From_XML.py`` in
``/home/G39248410/citizen_voice/Code/``. This module re-exports the public
API under the new package layout so callers can do
``from parser.uslm_parser import extract_public_law_from_uslm``.
"""
import sys
from pathlib import Path

_CODE_DIR = str(Path("/home/G39248410/citizen_voice/Code").resolve())
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from Extract_Sections_Divisions_From_XML import (  # noqa: E402
    extract_public_law_from_uslm,
    get_clean_text,
)

__all__ = ["extract_public_law_from_uslm", "get_clean_text"]
