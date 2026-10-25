"""Sign up, sign in and sign out with a password. Requests then send Authorization: Bearer <token>."""

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select

from app.api.deps import Db, SignedInUser
from app.config import get_settings
from app.db.models import User
from app.schemas import AuthOut, LoginIn, MeOut, SignupIn
from app.services import accounts

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_out(user: User) -> AuthOut:
    try:
        token, expires = accounts.make_token(get_settings(), user.id)
    except accounts.AuthNotConfigured as e:
        raise HTTPException(503, str(e)) from e
    return AuthOut(token=token, expires_at=datetime.fromtimestamp(expires, UTC), user=MeOut.model_validate(user))


@router.post("/signup", response_model=AuthOut, status_code=201)
async def signup(body: SignupIn, db: Db) -> AuthOut:
    """Create an account. Emails listed in DEV_EMAILS become dev accounts."""
    email = body.email.lower()
    taken = await db.scalar(
        select(User).where(or_(func.lower(User.username) == body.username.lower(), User.email == email))
    )
    if taken is not None:
        raise HTTPException(409, "Email already registered" if taken.email == email else "Username taken")
    user = User(
        username=body.username,
        email=email,
        password_hash=await run_in_threadpool(accounts.hash_password, body.password),
        is_dev=accounts.is_dev_email(get_settings(), email),
        avatar_url=f"https://api.dicebear.com/9.x/bottts/png?seed={quote(body.username)}",
    )
    db.add(user)
    await db.commit()
    return _auth_out(user)


@router.post("/login", response_model=AuthOut)
async def login(body: LoginIn, db: Db) -> AuthOut:
    """Sign in with username or email."""
    ident = body.login.strip()
    user = await db.scalar(
        select(User).where(or_(func.lower(User.username) == ident.lower(), User.email == ident.lower()))
    )
    ok = user is not None and await run_in_threadpool(accounts.verify_password, body.password, user.password_hash)
    if not ok:
        raise HTTPException(401, "Wrong username/email or password")
    # Picks up emails added to DEV_EMAILS after the account was made.
    is_dev = accounts.is_dev_email(get_settings(), user.email)
    if user.is_dev != is_dev:
        user.is_dev = is_dev
        await db.commit()
    return _auth_out(user)


@router.get("/me", response_model=MeOut)
async def me(account: SignedInUser) -> MeOut:
    """The signed-in account (not whoever a dev account is acting as)."""
    if account is None:
        raise HTTPException(401, "Not signed in")
    return MeOut.model_validate(account)


@router.post("/logout", status_code=204)
async def logout() -> Response:
    """Tokens are stateless, so signing out means the client drops its token."""
    return Response(status_code=204)
