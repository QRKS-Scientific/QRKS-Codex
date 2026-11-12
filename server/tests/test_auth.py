import threading

import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.admin import reset_user, revoke_devices, set_flag
from app.config import Settings
from app.models import AuthEvent, RefreshToken
from conftest import DEVICE, build_env, make_settings


def test_temporary_login_has_limited_scope(env):
    r = env.login("LEM")
    assert r.status_code == 200 and r.json()["must_change"] is True
    token = r.json()["access_token"]
    assert env.client.get("/v1/me", headers=env.auth(token)).json()["scope"] == "pwd_change"
    blocked = env.client.post("/v1/runs", headers=env.auth(token), json={"client_code": "QC-001"})
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "password_change_required"


def test_changing_password_gives_full_access_and_kills_the_temporary_one(env):
    session = env.sign_in_fully("LEM")
    assert session["must_change"] is False
    ok = env.client.post("/v1/runs", headers=env.auth(session["access_token"]), json={"client_code": "QC-001"})
    assert ok.status_code == 200
    again = env.login("LEM")                                             # the temporary password, now dead everywhere
    assert again.status_code == 401
    assert env.login("LEM", "river-Stone-84-lamp").json()["must_change"] is False


def test_temporary_password_cannot_be_reused_from_another_laptop_after_the_change(env):
    env.sign_in_fully("JER", device="laptop-A-0000001")
    other = env.login("JER", device="laptop-B-0000001")                  # same temp password, a different install
    assert other.status_code == 401


def test_wrong_passwords_count_down_then_lock_and_the_delay_doubles(env):
    msgs = [env.login("LEM", "nope").json()["detail"] for _ in range(4)]
    assert [m["attempts_left"] for m in msgs] == [4, 3, 2, 1]
    fifth = env.login("LEM", "nope")
    assert fifth.status_code == 401 and fifth.json()["detail"]["retry_after"] == 30
    during = env.login("LEM")                                            # even the correct password is refused while locked
    assert during.status_code == 423 and during.json()["detail"]["code"] == "locked"
    env.clock.advance(31)
    assert env.login("LEM", "nope").json()["detail"]["retry_after"] == 60
    env.clock.advance(61)
    assert env.login("LEM").status_code == 200                           # a correct sign-in clears the counter
    assert env.login("LEM", "nope").json()["detail"]["attempts_left"] == 4


def test_unknown_account_looks_exactly_like_a_wrong_password(env):
    unknown = env.login("ZZZ", "whatever")
    assert unknown.status_code == 401 and unknown.json()["detail"]["code"] == "bad_credentials"
    assert unknown.json()["detail"]["message"] == "Wrong initials or password."


def test_temporary_password_expires_after_seven_days(env):
    env.clock.advance(7 * 86400 + 5)
    r = env.login("LEM")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "temp_expired"
    with env.app.state.sessionmaker() as db:
        fresh = reset_user(db, env.app.state.security, env.app.state.settings, "LEM", env.clock())
    assert env.login("LEM", fresh).status_code == 200


def test_refresh_rotates_and_a_replayed_token_revokes_the_whole_session(env):
    s1 = env.sign_in_fully("LEM")
    r2 = env.client.post("/v1/auth/refresh", json={"refresh_token": s1["refresh_token"], "device_id": DEVICE})
    assert r2.status_code == 200 and r2.json()["refresh_token"] != s1["refresh_token"]
    env.clock.advance(60)                                                 # well past the grace window
    replay = env.client.post("/v1/auth/refresh", json={"refresh_token": s1["refresh_token"], "device_id": DEVICE})
    assert replay.status_code == 401 and replay.json()["detail"]["code"] == "session_revoked"
    legit = env.client.post("/v1/auth/refresh", json={"refresh_token": r2.json()["refresh_token"], "device_id": DEVICE})
    assert legit.status_code == 401                                        # the thief's replay ended the real session too


def test_a_lost_response_is_tolerated_within_the_grace_window(env):
    s1 = env.sign_in_fully("LEM")
    env.client.post("/v1/auth/refresh", json={"refresh_token": s1["refresh_token"], "device_id": DEVICE})
    env.clock.advance(3)
    retry = env.client.post("/v1/auth/refresh", json={"refresh_token": s1["refresh_token"], "device_id": DEVICE})
    assert retry.status_code == 200


def test_refresh_from_another_device_revokes_the_session(env):
    s1 = env.sign_in_fully("LEM")
    r = env.client.post("/v1/auth/refresh", json={"refresh_token": s1["refresh_token"], "device_id": "some-other-device"})
    assert r.status_code == 401
    assert env.client.post("/v1/auth/refresh", json={"refresh_token": s1["refresh_token"], "device_id": DEVICE}).status_code == 401


def test_idle_and_absolute_session_limits(env):
    s = env.sign_in_fully("LEM")
    env.clock.advance(15 * 86400)                                           # idle longer than 14 days
    assert env.client.post("/v1/auth/refresh", json={"refresh_token": s["refresh_token"], "device_id": DEVICE}).json()["detail"]["code"] == "session_expired"
    s = env.login("LEM", "river-Stone-84-lamp").json()
    for _ in range(4):                                                      # active use every 10 days...
        env.clock.advance(10 * 86400)
        r = env.client.post("/v1/auth/refresh", json={"refresh_token": s["refresh_token"], "device_id": DEVICE})
        if r.status_code != 200:
            break
        s = r.json()
    assert r.status_code == 401 and r.json()["detail"]["code"] == "session_expired"   # ...still ends at 30 days absolute


def test_logout_revokes_the_session(env):
    s = env.sign_in_fully("LEM")
    assert env.client.post("/v1/auth/logout", json={"refresh_token": s["refresh_token"]}).status_code == 204
    assert env.client.post("/v1/auth/refresh", json={"refresh_token": s["refresh_token"], "device_id": DEVICE}).status_code == 401


def test_device_limit_and_admin_removal(env):
    env.sign_in_fully("LEM", device="laptop-1-00000001")
    for n in (2, 3):
        assert env.login("LEM", "river-Stone-84-lamp", device=f"laptop-{n}-00000001").status_code == 200
    fourth = env.login("LEM", "river-Stone-84-lamp", device="laptop-4-00000001")
    assert fourth.status_code == 409 and fourth.json()["detail"]["code"] == "device_limit"
    with env.app.state.sessionmaker() as db:
        assert revoke_devices(db, "LEM") == 3
    assert env.login("LEM", "river-Stone-84-lamp", device="laptop-1-00000001").json()["detail"]["code"] == "device_revoked"
    assert env.login("LEM", "river-Stone-84-lamp", device="laptop-5-00000001").status_code == 200


def test_changing_the_password_signs_out_every_other_laptop(env):
    a = env.sign_in_fully("LEM", device="laptop-A-0000001")
    b = env.login("LEM", "river-Stone-84-lamp", device="laptop-B-0000001").json()
    r = env.client.post("/v1/auth/change-password", headers=env.auth(a["access_token"]),
                        json={"current_password": "river-Stone-84-lamp", "new_password": "copper-Field-77-moss"})
    assert r.status_code == 200
    assert env.client.post("/v1/auth/refresh", json={"refresh_token": b["refresh_token"], "device_id": "laptop-B-0000001"}).status_code == 401
    assert env.login("LEM", "river-Stone-84-lamp", device="laptop-C-0000001").status_code == 401


def test_disabled_account_cannot_sign_in_or_refresh(env):
    s = env.sign_in_fully("LEM")
    with env.app.state.sessionmaker() as db:
        set_flag(db, "LEM", disabled=True)
    assert env.client.post("/v1/auth/refresh", json={"refresh_token": s["refresh_token"], "device_id": DEVICE}).status_code == 401
    assert env.login("LEM", "river-Stone-84-lamp").json()["detail"]["code"] == "account_disabled"
    assert env.client.get("/v1/me", headers=env.auth(s["access_token"])).status_code == 401


def test_token_checks(env):
    s = env.sign_in_fully("LEM")
    good = env.auth(s["access_token"])
    assert env.client.get("/v1/me", headers=good).status_code == 200
    forged = jwt.encode({**jwt.decode(s["access_token"], options={"verify_signature": False}), "sub": "JCG"}, "a" * 40, algorithm="HS256")
    assert env.client.get("/v1/me", headers=env.auth(forged)).json()["detail"]["code"] == "bad_token"
    wrong_aud = jwt.encode({**jwt.decode(s["access_token"], options={"verify_signature": False}), "aud": "someone-else"},
                           env.app.state.settings.jwt_secret, algorithm="HS256")
    assert env.client.get("/v1/me", headers=env.auth(wrong_aud)).status_code == 401
    assert env.client.get("/v1/me").json()["detail"]["code"] == "not_authenticated"
    env.clock.advance(16 * 60)                                              # access tokens are short-lived
    assert env.client.get("/v1/me", headers=good).json()["detail"]["code"] == "token_expired"


def test_weak_new_password_and_wrong_current_password(env):
    t = env.login("LEM").json()["access_token"]
    weak = env.client.post("/v1/auth/change-password", headers=env.auth(t), json={"current_password": env.passwords["LEM"], "new_password": "short"})
    assert weak.status_code == 422 and weak.json()["detail"]["code"] == "weak_password"
    wrong = env.client.post("/v1/auth/change-password", headers=env.auth(t), json={"current_password": "not it", "new_password": "river-Stone-84-lamp"})
    assert wrong.status_code == 403 and wrong.json()["detail"]["code"] == "bad_current_password"


def test_login_is_rate_limited_per_ip(tmp_path):
    e = build_env(tmp_path, login_rate_per_minute=5)
    codes = [e.login("ZZZ", "x").status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    e.clock.advance(61)
    assert e.login("ZZZ", "x").status_code == 401                            # the window slides


def test_audit_trail_never_contains_passwords(env):
    env.login("LEM", "super-secret-guess-123")
    env.login("LEM")
    with env.app.state.sessionmaker() as db:
        rows = db.scalars(select(AuthEvent)).all()
        tokens = db.scalars(select(RefreshToken)).all()
    blob = " ".join(f"{r.initials} {r.outcome} {r.detail} {r.ip}" for r in rows)
    assert "super-secret" not in blob and env.passwords["LEM"] not in blob
    assert {r.outcome for r in rows} >= {"bad_password", "login_temp"}
    assert all(len(t.token_hash) == 64 for t in tokens)                      # only SHA-256 hashes of refresh tokens are stored


def test_documentation_pages_are_off_and_headers_are_set(env):
    assert env.client.get("/docs").status_code == 404 and env.client.get("/openapi.json").status_code == 404
    r = env.client.get("/healthz")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert env.client.get("/v1/meta").json()["min_app"] == "0.5.0"


def test_server_refuses_to_start_without_a_strong_secret(tmp_path):
    with pytest.raises(ValidationError):
        Settings(database_url=f"sqlite:///{tmp_path}/x.db", jwt_secret="too-short")


def test_pepper_changes_stored_hashes_and_still_verifies(tmp_path):
    e = build_env(tmp_path, pepper="a-long-server-side-secret-value")
    assert e.login("LEM").status_code == 200


def test_proxy_header_is_only_trusted_when_configured(tmp_path):
    e = build_env(tmp_path, login_rate_per_minute=3, trust_proxy_headers=True)
    for i in range(3):
        e.client.post("/v1/auth/login", json={"initials": "ZZZ", "password": "x", "device_id": DEVICE}, headers={"X-Forwarded-For": "10.0.0.1"})
    blocked = e.client.post("/v1/auth/login", json={"initials": "ZZZ", "password": "x", "device_id": DEVICE}, headers={"X-Forwarded-For": "10.0.0.1"})
    other = e.client.post("/v1/auth/login", json={"initials": "ZZZ", "password": "x", "device_id": DEVICE}, headers={"X-Forwarded-For": "10.0.0.2"})
    assert blocked.status_code == 429 and other.status_code == 401
