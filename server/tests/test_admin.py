import json
from pathlib import Path

from sqlalchemy import select

from app import admin
from app.models import User
from conftest import DEVICE, ROSTER, build_env


def test_init_creates_all_six_with_distinct_temporary_passwords(env):
    assert set(env.passwords) == {"LEM", "JER", "LPA", "JCG", "JML", "ERD"}
    assert len(set(env.passwords.values())) == 6
    with env.app.state.sessionmaker() as db:
        users = {u.initials: u for u in db.scalars(select(User))}
        assert all(u.must_change and u.temp_expires_at for u in users.values())
        assert users["LEM"].display_name == "Lars E. Medice, RCh." and users["ERD"].display_name.endswith(", RCh.")
        assert env.passwords["LEM"] not in users["LEM"].password_hash          # stored hashed, never readable
        assert admin.create_users(db, env.app.state.security, env.app.state.settings, ROSTER, env.clock()) == {}   # idempotent


def test_server_roster_names_come_back_in_me(env):
    s = env.sign_in_fully("JCG")
    me = env.client.get("/v1/me", headers=env.auth(s["access_token"])).json()
    assert me["display_name"] == "Josiah C. Guillermo, RCh." and me["role"] == "Finance Lead" and me["scope"] == "full"


def test_reset_signs_the_lead_out_everywhere_and_issues_a_new_temporary_password(env):
    s = env.sign_in_fully("JER")
    with env.app.state.sessionmaker() as db:
        fresh = admin.reset_user(db, env.app.state.security, env.app.state.settings, "JER", env.clock())
    assert env.client.post("/v1/auth/refresh", json={"refresh_token": s["refresh_token"], "device_id": DEVICE}).status_code == 401
    assert env.login("JER", "river-Stone-84-lamp").status_code == 401           # the chosen password is replaced too
    assert env.login("JER", fresh).json()["must_change"] is True


def test_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("QRKS_DATABASE_URL", f"sqlite:///{tmp_path}/cli.db")
    monkeypatch.setenv("QRKS_JWT_SECRET", "x" * 40)
    monkeypatch.setenv("QRKS_ARGON2_MEMORY_KIB", "64")
    monkeypatch.setenv("QRKS_ARGON2_TIME_COST", "1")
    roster = Path(__file__).resolve().parents[1] / "roster.json"
    assert admin.main(["init", "--roster", str(roster)]) == 0
    out = capsys.readouterr().out
    assert sum(1 for line in out.splitlines() if line[:3] in {"LEM", "JER", "LPA", "JCG", "JML", "ERD"}) == 6
    assert admin.main(["list"]) == 0 and "Lars E. Medice, RCh." in capsys.readouterr().out
    assert admin.main(["reset", "JER"]) == 0 and "JER" in capsys.readouterr().out
    assert admin.main(["reset", "ZZZ"]) == 1
    assert admin.main(["disable", "LPA"]) == 0 and admin.main(["list"]) == 0
    assert "disabled" in capsys.readouterr().out
    assert admin.main(["audit"]) == 0
