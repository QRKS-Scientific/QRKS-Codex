import json
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.admin import create_users
from app.config import Settings
from app.main import create_app

ROSTER = json.loads((Path(__file__).resolve().parents[1] / "roster.json").read_text(encoding="utf-8"))
DEVICE = "laptop-0001-aaaa"


class Clock:
    """A clock the tests can move forward, so lockouts and expiries are tested without waiting."""
    def __init__(self, t: float = 1794086400.0):          # 2026-11-07 21:20 UTC = 2026-11-08 05:20 in Manila
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def make_settings(tmp_path, **over) -> Settings:
    base = dict(database_url=f"sqlite:///{tmp_path}/t.db", jwt_secret=secrets.token_hex(32), argon2_time_cost=1,
                argon2_memory_kib=64, login_rate_per_minute=1000, api_rate_per_minute=100000)
    base.update(over)
    return Settings(**base)


class Env:
    def __init__(self, app, clock, passwords):
        self.app, self.clock, self.passwords = app, clock, passwords
        self.client = TestClient(app)

    def login(self, ini="LEM", password=None, device=DEVICE, client=None):
        return (client or self.client).post("/v1/auth/login", json={"initials": ini, "password": password or self.passwords[ini],
                                                                    "device_id": device, "device_name": "Test laptop"})

    def auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def sign_in_fully(self, ini="LEM", device=DEVICE, new_password="river-Stone-84-lamp"):
        """Temporary password -> own password -> full-scope tokens."""
        first = self.login(ini, device=device).json()
        r = self.client.post("/v1/auth/change-password", headers=self.auth(first["access_token"]),
                             json={"current_password": self.passwords[ini], "new_password": new_password})
        assert r.status_code == 200, r.text
        return r.json()


def build_env(tmp_path, **over) -> Env:
    clock = Clock()
    app = create_app(make_settings(tmp_path, **over), clock)
    with app.state.sessionmaker() as db:
        passwords = create_users(db, app.state.security, app.state.settings, ROSTER, clock())
    return Env(app, clock, passwords)


@pytest.fixture()
def env(tmp_path):
    return build_env(tmp_path)
