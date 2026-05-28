"""Tests for parser.law_id_utils.normalize_law_id."""
import pytest

from parser.law_id_utils import normalize_law_id


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Public Law 106-171", "106-171"),
        ("Public Law 106–171", "106-171"),   # en-dash
        ("Public Law 106—171", "106-171"),   # em-dash
        ("79-294", "79-294"),
        ("104–9", "104-9"),
        ("Public Law  106 - 171", "106-171"),
    ],
)
def test_normalize_law_id_canonical(raw, expected):
    assert normalize_law_id(raw) == expected


def test_normalize_law_id_no_pattern_passthrough():
    assert normalize_law_id("garbage no numbers here") == "garbage no numbers here"


def test_normalize_law_id_empty():
    assert normalize_law_id("") == ""


def test_normalize_law_id_none():
    assert normalize_law_id(None) == ""
