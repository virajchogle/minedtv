import uuid

from app.services.redis import get_queue

PIPELINE_JOB = "app.worker.jobs.process_session"


def enqueue_pipeline(session_id: uuid.UUID, resume: bool = False) -> str:
    job = get_queue().enqueue(
        PIPELINE_JOB,
        str(session_id),
        resume=resume,
        job_id=f"pipeline-{session_id}-{uuid.uuid4().hex[:8]}",
        result_ttl=3600,
        failure_ttl=86400,
    )
    return job.id


def enqueue_export(clip_id: uuid.UUID) -> str:
    job = get_queue().enqueue(
        "app.worker.jobs.export_clip",
        str(clip_id),
        job_id=f"export-{clip_id}-{uuid.uuid4().hex[:8]}",
        job_timeout=900,
        result_ttl=3600,
        failure_ttl=86400,
    )
    return job.id


def enqueue_creator_pack(clip_id: uuid.UUID) -> str:
    job = get_queue().enqueue(
        "app.worker.jobs.creator_pack",
        str(clip_id),
        job_id=f"creator-{clip_id}-{uuid.uuid4().hex[:8]}",
        job_timeout=1500,  # export + Gemini, including model fallbacks
        result_ttl=3600,
        failure_ttl=86400,
    )
    return job.id


def enqueue_frame_highlights(
    session_id: uuid.UUID, requested_count: int, clip_duration_ms: int, make_clips: bool = True
) -> str:
    job = get_queue().enqueue(
        "app.worker.jobs.frame_highlights",
        str(session_id),
        requested_count=requested_count,
        clip_duration_ms=clip_duration_ms,
        make_clips=make_clips,
        job_id=f"frame-highlights-{session_id}-{uuid.uuid4().hex[:8]}",
        job_timeout=900,
        result_ttl=3600,
        failure_ttl=86400,
    )
    return job.id


def enqueue_youtube_post(upload_id: uuid.UUID) -> str:
    job = get_queue().enqueue(
        "app.worker.jobs.youtube_post",
        str(upload_id),
        job_id=f"youtube-{upload_id}",
        job_timeout=1800,  # export + upload
        result_ttl=3600,
        failure_ttl=86400,
    )
    return job.id
