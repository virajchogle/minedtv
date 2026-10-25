"""Password accounts, login tokens and who a request acts as."""

import uuid

import pytest
from fastapi import HTTPException

from app.api import accounts as accounts_api
from app.api import deps
from app.config import Settings, get_settings
from app.db.models import User
from app.schemas import LoginIn, SignupIn
from app.services import accounts
from tests.test_pipeline_e2e import migrated_db, sessionmaker  # noqa: F401  (fixtures)


def auth_settings(**kw) -> Settings:
    return get_settings().model_copy(update={"auth_secret": "s3cret", "dev_emails": ["dev@team.gg"], **kw})


@pytest.fixture
def settings(monkeypatch):
    s = auth_settings()
    for mod in (deps, accounts_api):
        monkeypatch.setattr(mod, "get_settings", lambda: s)
    return s


def test_password_hash_round_trip():
    stored = accounts.hash_password("hunter22!")
    assert stored.startswith("scrypt$") and "hunter22" not in stored
    assert accounts.verify_password("hunter22!", stored)
    assert not accounts.verify_password("hunter23!", stored)
    assert not accounts.verify_password("x", None) and not accounts.verify_password("x", "garbage")


def test_token_round_trip_expiry_and_tampering():
    s = auth_settings()
    uid = uuid.uuid4()
    token, exp = accounts.make_token(s, uid, now=1_000)
    assert accounts.read_token(s, token, now=2_000) == uid
    with pytest.raises(accounts.InvalidToken, match="expired"):
        accounts.read_token(s, token, now=exp + 1)
    with pytest.raises(accounts.InvalidToken):
        accounts.read_token(auth_settings(auth_secret="other"), token, now=2_000)
    other = uuid.uuid4()
    with pytest.raises(accounts.InvalidToken):
        accounts.read_token(s, token.replace(str(uid), str(other)), now=2_000)
    with pytest.raises(accounts.AuthNotConfigured):
        accounts.make_token(Settings(), uid)


async def _resolve(db, token: str | None, x_user_id: uuid.UUID | None):
    account = await deps.signed_in_user(db, f"Bearer {token}" if token else None)
    return await deps.current_user_optional(db, account, x_user_id)


async def test_signup_login_and_acting_as(sessionmaker, settings):  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    async with sessionmaker() as db:
        dev = await accounts_api.signup(SignupIn(username=f"dev_{tag}", email=f"DEV@team.gg", password="password1"), db)
        player = await accounts_api.signup(
            SignupIn(username=f"p_{tag}", email=f"p_{tag}@mail.com", password="password2"), db
        )
        demo = User(username=f"demo_{tag}")
        db.add(demo)
        await db.commit()
    assert dev.user.is_dev and dev.user.email == "dev@team.gg" and not player.user.is_dev

    async with sessionmaker() as db:
        with pytest.raises(HTTPException) as e:
            await accounts_api.signup(SignupIn(username=f"P_{tag}", email="new@mail.com", password="password3"), db)
        assert e.value.status_code == 409  # usernames are case-insensitive
        with pytest.raises(HTTPException) as e:
            await accounts_api.login(LoginIn(login=f"p_{tag}", password="wrong-pass"), db)
        assert e.value.status_code == 401
        again = await accounts_api.login(LoginIn(login=f"P_{tag}@MAIL.com", password="password2"), db)
        assert again.user.id == player.user.id

        # A token alone acts as its account.
        assert (await _resolve(db, player.token, None)).id == player.user.id
        assert (await _resolve(db, player.token, player.user.id)).id == player.user.id
        with pytest.raises(HTTPException) as e:
            await _resolve(db, "not-a-token", None)
        assert e.value.status_code == 401

        # Testing mode (REQUIRE_LOGIN off): anyone, signed in or not, may act as anyone.
        assert (await _resolve(db, None, demo.id)).id == demo.id
        assert (await _resolve(db, player.token, demo.id)).id == demo.id
        assert (await accounts_api.me(await db.get(User, player.user.id))).can_act_as

        # REQUIRE_LOGIN on: a token is needed, and only dev accounts may act as someone else.
        settings.require_login = True
        with pytest.raises(HTTPException) as e:
            await _resolve(db, None, demo.id)
        assert e.value.status_code == 401
        with pytest.raises(HTTPException) as e:
            await _resolve(db, player.token, demo.id)
        assert e.value.status_code == 403
        assert (await _resolve(db, dev.token, demo.id)).id == demo.id
        assert not (await accounts_api.me(await db.get(User, player.user.id))).can_act_as
        assert (await accounts_api.me(await db.get(User, dev.user.id))).can_act_as
