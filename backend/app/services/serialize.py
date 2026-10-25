"""DB rows -> response models. Keeps URL building in one place."""

import uuid

from app.api.deps import UrlBuilder
from app.db.models import Clip, Session, User
from app.schemas import ClipOut, SessionOut, UserOut
from app.services.storage import get_storage


def user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


def url_or_none(key: str | None) -> str | None:
    return get_storage().url_for(key) if key else None


def clip_out(
    clip: Clip,
    session: Session,
    user: User,
    urls: UrlBuilder,
    pending: tuple[int, int] = (0, 0),
    liked_ids: set[uuid.UUID] | None = None,
    comment_count: int = 0,
    youtube_url: str | None = None,
) -> ClipOut:
    return ClipOut(
        id=clip.id,
        session_id=clip.session_id,
        user=user_out(user),
        game=session.game,
        title=clip.title,
        start_ms=clip.start_ms,
        end_ms=clip.end_ms,
        duration_ms=clip.end_ms - clip.start_ms,
        thumbnail_url=url_or_none(clip.thumbnail_key or session.poster_key),
        playlist_url=urls.clip_playlist(clip.id),
        status=clip.status,
        kind=clip.kind,
        publish_state=clip.publish_state,
        published_at=clip.published_at,
        view_count=clip.view_count + pending[0],
        like_count=clip.like_count + pending[1],
        liked_by_me=None if liked_ids is None else clip.id in liked_ids,
        comment_count=comment_count,
        youtube_url=youtube_url,
        age_restricted=clip.age_restricted,
        moderation_severity=session.moderation_severity,
        moderation_reason=session.moderation_reason,
        moderation_violations=clip.moderation_violations,
        created_at=clip.created_at,
    )


def session_out(session: Session, user: User, urls: UrlBuilder) -> SessionOut:
    return SessionOut(
        id=session.id,
        user=user_out(user),
        game=session.game,
        title=session.title,
        started_at=session.started_at,
        duration_ms=session.duration_ms,
        width=session.width,
        height=session.height,
        status=session.status,
        last_step=session.last_step,
        failed_step=session.failed_step,
        error=session.error,
        poster_url=url_or_none(session.poster_key),
        playlist_url=urls.session_playlist(session.id) if session.status == "ready" else None,
        created_at=session.created_at,
        moderation_severity=session.moderation_severity,
        moderation_reason=session.moderation_reason,
        age_restricted=session.age_restricted,
        moderation_violations=session.moderation_violations,
    )
