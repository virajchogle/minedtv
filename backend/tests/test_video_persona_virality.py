from pathlib import Path

from app.config import get_settings
from app.schemas import CreatorPackOut
from app.services.frame_virality import clear_prompt_cache
from app.services.video_persona_virality import VideoPersonaViralityEngine
from app.worker.media import ProbeResult


class FakeEmbedder:
    dim = 2

    def embed_images(self, images):
        return [[1.0, 0.0] if image == b"peak" else [0.0, 1.0] for image in images]

    def embed_texts(self, texts):
        return [[1.0, 0.0] for _ in texts[:-1]] + [[0.0, 1.0]]


def _analysis() -> CreatorPackOut:
    return CreatorPackOut.model_validate(
        {
            "title_options": ["The finish"],
            "description": "A player sets up and wins the round.",
            "summary": "The round ends in a clutch.",
            "caption": "Wait for the finish.",
            "youtube": {
                "title": "The finish",
                "description": "A full round.",
                "tags": ["gaming"],
                "chapters": [{"timestamp": "00:00", "label": "Round"}],
            },
            "reddit": {"title": "The finish", "body": "Full round", "suggested_subreddits": ["gaming"]},
            "transcript": [
                {"timestamp": "00:02", "text": "Hold on."},
                {"timestamp": "00:06", "text": "No way! Let's go!"},
            ],
            "key_moments": [{"timestamp": "00:06", "label": "Clutch win"}],
            "hashtags": ["gaming"],
            "content_warnings": [],
        }
    )


def test_video_persona_evidence_samples_once_and_explains_peaks(tmp_path, monkeypatch):
    from app.services import video_persona_virality as module

    clear_prompt_cache()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    calls = {"samples": 0, "image_batches": 0}

    def sample_frames(src, out_dir, *, fps, width):
        calls["samples"] += 1
        out_dir.mkdir(parents=True, exist_ok=True)
        sampled = []
        for index, content in enumerate((b"plain", b"plain", b"peak", b"peak", b"plain")):
            path = out_dir / f"{index}.jpg"
            path.write_bytes(content)
            sampled.append((index * 2000, path))
        return sampled

    class CountingEmbedder(FakeEmbedder):
        def embed_images(self, images):
            calls["image_batches"] += 1
            return super().embed_images(images)

    monkeypatch.setattr(module.media, "tools_available", lambda: True)
    monkeypatch.setattr(module.media, "probe", lambda path: ProbeResult(10_000, 1280, 720, 30, True))
    monkeypatch.setattr(module.media, "sample_frames", sample_frames)
    monkeypatch.setattr(module, "image_visibility_score", lambda image: 1.0)

    settings = get_settings().model_copy(
        update={"creator_virality_sample_fps": 0.5, "embed_batch_size": 32}
    )
    engine = VideoPersonaViralityEngine(settings, CountingEmbedder())
    prepared = engine.prepare(source)
    evidence = engine.evidence(prepared, _analysis())

    assert calls == {"samples": 1, "image_batches": 1}
    assert evidence.frames_analyzed == 5
    assert 0 <= evidence.frame_score <= 100
    assert evidence.peak_score >= evidence.sustained_score
    assert evidence.moments
    assert any(moment.t_ms in (4000, 6000) for moment in evidence.moments)
    assert all(moment.context_start_ms < moment.context_end_ms for moment in evidence.moments)
    assert not any(Path(tmp_path).glob("minedtv-persona-frames-*"))


def test_timestamp_parser_supports_minute_and_hour_formats():
    from app.services.video_persona_virality import _timestamp_ms

    assert _timestamp_ms("01:02") == 62_000
    assert _timestamp_ms("1:02:03.5") == 3_723_500
    assert _timestamp_ms("bad") is None


def test_long_video_sampling_is_capped(tmp_path, monkeypatch):
    from app.services import video_persona_virality as module

    source = tmp_path / "long.mp4"
    source.write_bytes(b"video")
    captured = {}

    def sample_frames(src, out_dir, *, fps, width):
        captured["fps"] = fps
        path = out_dir / "0.jpg"
        path.write_bytes(b"plain")
        return [(0, path)]

    monkeypatch.setattr(module.media, "tools_available", lambda: True)
    monkeypatch.setattr(module.media, "probe", lambda path: ProbeResult(600_000, 1280, 720, 30, True))
    monkeypatch.setattr(module.media, "sample_frames", sample_frames)
    monkeypatch.setattr(module, "image_visibility_score", lambda image: 1.0)
    settings = get_settings().model_copy(
        update={"creator_virality_sample_fps": 0.5, "creator_virality_max_frames": 60}
    )

    VideoPersonaViralityEngine(settings, FakeEmbedder()).prepare(source)

    assert captured["fps"] == 0.1
