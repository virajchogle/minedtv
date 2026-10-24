"""Structured JSON logging. Any log line emitted while a session is bound carries its session_id."""

import contextvars
import json
import logging
import sys
from contextlib import contextmanager
from datetime import UTC, datetime

_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)
_step: contextvars.ContextVar[str | None] = contextvars.ContextVar("step", default=None)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


@contextmanager
def bind(session_id: str | None = None, step: str | None = None):
    tokens = []
    if session_id is not None:
        tokens.append((_session_id, _session_id.set(str(session_id))))
    if step is not None:
        tokens.append((_step, _step.set(step)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.session_id = getattr(record, "session_id", None) or _session_id.get()
        record.step = getattr(record, "step", None) or _step.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and value is not None and not key.startswith("_"):
                out[key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {k: v for k, v in record.__dict__.items() if k not in _RESERVED and v is not None and not k.startswith("_")}
        ctx = " ".join(f"{k}={v}" for k, v in extras.items())
        return f"{base} [{ctx}]" if ctx else base


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_ContextFilter())
    handler.setFormatter(_JsonFormatter() if json_logs else _TextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("botocore", "boto3", "urllib3", "s3transfer", "httpx", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
