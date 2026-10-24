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
