"""Normalize law identifiers across legacy and modern USLM formats."""
import re

_LAW_ID_RE = re.compile(r"(\d+)\s*[–—\-]\s*(\d+)")


def normalize_law_id(raw_id):
    """Return canonical ``{congress}-{number}`` form (ASCII hyphen).

    Examples:
        'Public Law 106-171' -> '106-171'
        'Public Law 106–171' -> '106-171'   # en-dash -> hyphen
        '79-294' -> '79-294'
        '104–9' -> '104-9'

    Returns the input unchanged if no recognized pattern is found.
    ``None`` is coerced to ``''``.
    """
    if raw_id is None:
        return ""
    if not raw_id:
        return raw_id
    m = _LAW_ID_RE.search(str(raw_id))
    if not m:
        return raw_id
    return f"{m.group(1)}-{m.group(2)}"
