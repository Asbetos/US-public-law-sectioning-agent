"""P2: cv-coder finalize must be branch-aware — a task can target the pipeline
repo (default) or the standalone legacy-law-identity package.
"""
import importlib.util
from pathlib import Path

_MODULE = Path("/home/G39248410/citizen_voice/Code/data-preprocessing-pipeline/skills/cv-coder/finalize_implementation.py")
_spec = importlib.util.spec_from_file_location("finalize_implementation_ba", _MODULE)
fi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fi)


def test_repo_targets_defines_both_repos():
    assert "pipeline" in fi._REPO_TARGETS
    assert "legacy-law-identity" in fi._REPO_TARGETS
    # legacy package root is a sibling of the pipeline repo
    assert fi._REPO_TARGETS["legacy-law-identity"][0].name == "legacy-law-identity"


def test_default_scope_rejects_legacy_package_path():
    # Back-compat: with the default (pipeline) prefixes, a legacy-package edit
    # is out of scope and must be rejected.
    ok, err = fi._assert_scope_clean(["src/legacy_law_identity/resolver.py"])
    assert ok is False and "out-of-scope" in err


def test_legacy_prefixes_accept_resolver_and_tests():
    _, prefixes = fi._REPO_TARGETS["legacy-law-identity"]
    ok, err = fi._assert_scope_clean(
        ["src/legacy_law_identity/resolver.py", "tests/test_resolver.py"],
        prefixes,
    )
    assert ok is True and err is None


def test_forbidden_file_still_rejected_under_legacy_target():
    _, prefixes = fi._REPO_TARGETS["legacy-law-identity"]
    ok, err = fi._assert_scope_clean(["pipeline/corrections_registry.py"], prefixes)
    assert ok is False and "forbidden" in err
