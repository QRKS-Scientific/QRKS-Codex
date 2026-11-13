import json

import pytest

from qrksdock.core import accounts as acc
from qrksdock.core import rules
from qrksdock import paths

TEMP = {"LEM": "TEMP-LEM-0001", "JER": "TEMP-JER-0002"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def store(tmp_path, clock):
    shipped = tmp_path / "accounts.json"
    shipped.write_text(json.dumps({"version": 1, "accounts": {k: acc.hash_password(v, iterations=1000) for k, v in TEMP.items()}}))
    return acc.AccountStore(shipped_file=shipped, local_dir=tmp_path / "local", clock=clock)


def test_hashing_is_salted_and_checks_correctly():
    a, b = acc.hash_password("same password", 1000), acc.hash_password("same password", 1000)
    assert a["salt"] != b["salt"] and a["hash"] != b["hash"]
    assert acc.check_password("same password", a) and not acc.check_password("other", a)
    assert "same password" not in json.dumps(a)


def test_password_policy():
    problem = acc.password_problem("short")
    assert problem is not None and "at least" in problem
    problem = acc.password_problem("TEMP-LEM-0001", "TEMP-LEM-0001")
    assert problem is not None and "different" in problem
    assert acc.password_problem("aaaaaaaaaaaa")
    problem = acc.password_problem("my-lem-secret-99", "x", "LEM")
    assert problem is not None and "initials" in problem
    assert acc.password_problem("river-Stone-84-lamp", "TEMP-LEM-0001", "LEM") is None


def test_first_sign_in_requires_a_new_password_then_old_one_stops_working(store):
    first = store.authenticate("LEM", TEMP["LEM"])
    assert first.ok and first.must_change and store.needs_password_change("LEM")
    store.change_password("LEM", TEMP["LEM"], "river-Stone-84-lamp")
    assert not store.needs_password_change("LEM")
    again = store.authenticate("LEM", "river-Stone-84-lamp")
    assert again.ok and not again.must_change
    assert not store.authenticate("LEM", TEMP["LEM"]).ok                       # the temporary password is retired on this laptop
    assert store.authenticate("JER", TEMP["JER"]).must_change                  # other accounts are unaffected


def test_change_password_needs_the_current_password_and_a_good_new_one(store):
    with pytest.raises(ValueError, match="current password"):
        store.change_password("LEM", "wrong", "river-Stone-84-lamp")
    with pytest.raises(ValueError, match="at least"):
        store.change_password("LEM", TEMP["LEM"], "short")
    assert store.needs_password_change("LEM")                                  # nothing was saved


def test_wrong_password_counts_down_then_locks_with_growing_delay(store, clock):
    msgs = [store.authenticate("LEM", "nope") for _ in range(4)]
    assert [m.attempts_left for m in msgs] == [4, 3, 2, 1] and not any(m.locked_for for m in msgs)
    locked = store.authenticate("LEM", "nope")
    assert locked.locked_for == acc.BASE_LOCK_SECONDS and locked.attempts_left == 0
    during = store.authenticate("LEM", TEMP["LEM"])                            # even the right password is refused while locked
    assert not during.ok and during.locked_for > 0
    clock.now += acc.BASE_LOCK_SECONDS + 1
    second = store.authenticate("LEM", "nope")
    assert second.locked_for == acc.BASE_LOCK_SECONDS * 2                      # the delay doubles
    clock.now += 10_000
    assert store.authenticate("LEM", TEMP["LEM"]).ok                           # a correct sign-in clears the counter
    assert store.authenticate("LEM", "nope").attempts_left == 4


def test_empty_and_unknown(store):
    assert not store.authenticate("LEM", "").ok
    assert "does not exist" in store.authenticate("ZZZ", "x").message


def test_there_is_no_registration():
    assert not [n for n in dir(acc.AccountStore) if any(k in n.lower() for k in ("register", "signup", "sign_up", "create_account", "add_account"))]


def test_shipped_accounts_cover_the_six_leads_and_store_only_hashes():
    data = json.loads(paths.data_file("accounts.json").read_text())
    assert set(data["accounts"]) == {p["initials"] for p in rules.roster()} and len(data["accounts"]) == 6
    for rec in data["accounts"].values():
        assert set(rec) == {"salt", "hash", "iterations"} and rec["iterations"] >= 600_000
    store = acc.AccountStore()
    assert [a["initials"] for a in store.accounts()] == [p["initials"] for p in rules.roster()]


def test_make_accounts_script_format_and_distinct_passwords():
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_accounts", paths.base_dir() / "scripts" / "make_accounts.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pws = {mod.temp_password() for _ in range(200)}
    assert len(pws) == 200
    sample = next(iter(pws))
    assert len(sample) == 14 and sample.count("-") == 2 and not set(sample) & set("0O1I")
