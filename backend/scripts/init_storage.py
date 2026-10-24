"""Create the bucket if needed and set its CORS rules (browsers PUT uploads and fetch HLS
segments straight from storage, so the bucket must allow the web UI's origin).

    python -m scripts.init_storage
"""

import time

from app.config import get_settings
from app.services.storage import S3Storage


def main() -> None:
    settings = get_settings()
    if settings.storage_backend != "s3":
        return
    storage = S3Storage(settings)
    for attempt in range(30):
        try:
            storage.ensure_bucket()
            print(f"bucket {settings.s3_bucket} ready")
            break
        except Exception as e:  # noqa: BLE001 - server still starting
            if attempt == 29:
                raise
            print(f"waiting for storage: {e}")
            time.sleep(2)
    try:
        storage._client.put_bucket_cors(
            Bucket=settings.s3_bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedOrigins": settings.cors_origins,
                        "AllowedMethods": ["GET", "PUT", "HEAD"],
                        "AllowedHeaders": ["*"],
                        "ExposeHeaders": ["ETag", "Content-Length", "Content-Range"],
                        "MaxAgeSeconds": 3600,
                    }
                ]
            },
        )
        print(f"bucket CORS set for {settings.cors_origins}")
    except Exception as e:  # noqa: BLE001 - not every S3 implementation supports it
        print(f"could not set bucket CORS ({e}); set it in the provider's dashboard if the web UI needs it")


if __name__ == "__main__":
    main()
