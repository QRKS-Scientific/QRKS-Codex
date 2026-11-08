"""Locks in decisions the team made by hand, so a later build cannot silently undo them."""
import re

from qrksdock import paths
from qrksdock.core import rules


def test_all_six_leads_show_rch_with_a_period_everywhere():
    names = {p["initials"]: p["display_name"] for p in rules.roster()}
    assert names == {"LEM": "Lars E. Medice, RCh.", "JER": "John E. Rico, RCh.", "LPA": "Lester P. Abdon, RCh.",
                     "JCG": "Josiah C. Guillermo, RCh.", "JML": "Jason M. Llamera, RCh.", "ERD": "Erwin R. Desaliza, RCh."}
    for text in names.values():
        assert text.endswith(", RCh.") and not re.search(r"RCh(?!\.)", text)      # never 'RCh' without its period


def test_credential_is_data_and_display_name_is_built_in_one_place():
    for p in rules.roster():
        assert "RCh" not in p["name"]                                             # the plain name carries no title
        assert p["credential"] == "RCh." and p["display_name"] == f"{p['name']}, RCh."
    assert rules.display_name_of("LEM") == "Lars E. Medice, RCh."
    assert rules.display_name_of("ZZZ") == "ZZZ"


def test_rch_appears_on_the_login_tiles_header_and_report(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from test_app import _app, _win
    _app()
    win = _win(tmp_path)
    assert "Lars E. Medice, RCh." in win.login.tiles["LEM"].text()
    assert "Josiah C. Guillermo, RCh." in win.login.tiles["JCG"].text()
    assert all("RCh." in tile.text() for tile in win.login.tiles.values())        # all six tiles
    win.sign_in("JCG")
    assert win.user_name.text() == "Josiah C. Guillermo, RCh."
    assert "Josiah C. Guillermo, RCh." in win.status_lbl.text()


def test_locked_in_build_workflow():
    wf = (paths.base_dir() / ".github" / "workflows" / "build.yml").read_text()
    assert re.findall(r"- os: (\S+)", wf) == ["windows-latest", "macos-latest"]
    assert "pyinstaller packaging/qrksdock.spec" in wf
    assert (paths.base_dir() / "packaging" / "qrksdock.spec").exists()
