"""Worker entry point: `python -m app.worker [--burst]`.

--burst processes whatever is queued and exits (for a Cloud Run Job). Otherwise it runs
forever; if $PORT is set it also serves a tiny health endpoint so it can run as a Cloud
Run service.
"""

import argparse
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from rq import Worker

from app.config import get_settings
from app.log import setup_logging
from app.services.redis import get_queue, get_sync_redis


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--burst", action="store_true", help="exit when the queue is empty")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    if port := os.environ.get("PORT"):
        server = HTTPServer(("0.0.0.0", int(port)), _Health)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    worker = Worker([get_queue()], connection=get_sync_redis())
    worker.work(burst=args.burst, with_scheduler=False, logging_level=settings.log_level)


if __name__ == "__main__":
    main()
