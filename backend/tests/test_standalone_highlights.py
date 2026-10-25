from pathlib import Path

from app.config import get_settings
from app.services.frame_virality import clear_prompt_cache
from app.services.standalone_highlights import StandaloneHighlightEngine
from app.worker.media import ProbeResult


class FakeEmbedder:
    dim = 2

    def embed_images(self, images):
        return [[1.0, 0.0] if image == b"peak" else [0.0, 1.0] for image in images]

    def embed_texts(self, texts):
        return [[1.0, 0.0] for _ in texts[:-1]] + [[0.0, 1.0]]


def test_direct_engine_samples_once_and_renders_ranked_clips(tmp_path, monkeypatch):
    from app.services import standalone_highlights as module

    clear_prompt_cache()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    sampled_paths = []

    def sample_frames(src, out_dir, *, fps, width):
        out_dir.mkdir(parents=True)
        for index, content in enumerate((b"plain", b"peak", b"plain", b"peak", b"plain")):
            path = out_dir / f"{index}.jpg"
            path.write_bytes(content)
            sampled_paths.append(path)
        return [(index * 2000, path) for index, path in enumerate(sampled_paths)]

    rendered = []

    def render_mobile_clip(src, out, start_ms, end_ms, **kwargs):
        out.write_bytes(f"{start_ms}-{end_ms}".encode())
        rendered.append((start_ms, end_ms))
        return out

    monkeypatch.setattr(module.media, "tools_available", lambda: True)
    monkeypatch.setattr(module.media, "probe", lambda path: ProbeResult(10_000, 1280, 720, 30, True))
    monkeypatch.setattr(module.media, "sample_frames", sample_frames)
    monkeypatch.setattr(module.media, "render_mobile_clip", render_mobile_clip)
    monkeypatch.setattr(module, "image_visibility_score", lambda image: 1.0)

    settings = get_settings().model_copy(update={
        "standalone_highlight_dir": str(tmp_path / "output"),
        "standalone_highlight_sample_fps": 0.5,
        "frame_virality_min_score": 0.0,
    })
    result = StandaloneHighlightEngine(settings, FakeEmbedder()).process(source, "source.mp4")

    assert result.filename == "source.mp4"
    assert result.duration_ms == 10_000
    assert len(result.scores) == 5
    assert len(result.clips) == 1
    assert result.clips[0].title == "The viral clip"
    assert len(rendered) == len(result.clips)
    for clip in result.clips:
        assert (tmp_path / "output" / str(result.run_id) / "clips" / f"{clip.index}.mp4").is_file()
        assert (tmp_path / "output" / str(result.run_id) / "frames" / f"{clip.frame_id}.jpg").is_file()
        assert (clip.width, clip.height) == (720, 1280)
        assert clip.captions_burned is False


def test_direct_engine_burns_transcribed_captions(tmp_path, monkeypatch):
    from app.ml.interfaces import TranscriptChunk
    from app.services import standalone_highlights as module

    class FakeTranscriber:
        def transcribe(self, audio_path):
            assert Path(audio_path).is_file()
            return [TranscriptChunk(250, 1800, "Plant the defuser!")]

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    def sample_frames(src, out_dir, **kwargs):
        out_dir.mkdir(parents=True)
        path = out_dir / "frame.jpg"
        path.write_bytes(b"peak")
        return [(1000, path)]

    rendered = {}

    def extract_audio_range(src, out, start_ms, end_ms):
        assert (start_ms, end_ms) == (0, 8000)
        out.write_bytes(b"audio")
        return out

    def render_mobile_clip(src, out, start_ms, end_ms, **kwargs):
        rendered.update(kwargs)
        rendered["caption_text"] = kwargs["captions"].read_text(encoding="utf-8-sig")
        out.write_bytes(b"mobile")
        return out

    monkeypatch.setattr(module.media, "tools_available", lambda: True)
    monkeypatch.setattr(module.media, "probe", lambda path: ProbeResult(8_000, 1920, 1080, 60, True))
    monkeypatch.setattr(module.media, "sample_frames", sample_frames)
    monkeypatch.setattr(module.media, "extract_audio_range", extract_audio_range)
    monkeypatch.setattr(module.media, "render_mobile_clip", render_mobile_clip)
    monkeypatch.setattr(module, "image_visibility_score", lambda image: 1.0)

    settings = get_settings().model_copy(update={
        "standalone_highlight_dir": str(tmp_path / "output"),
        "frame_virality_min_score": 0.0,
    })
    result = StandaloneHighlightEngine(settings, FakeEmbedder(), FakeTranscriber()).process(source, "source.mp4")

    clip = result.clips[0]
    assert clip.captions_burned is True
    assert clip.caption_count == 1
    assert clip.caption_source == "transcriber"
    assert rendered["captions"].suffix == ".ass"
    assert "Plant the defuser!" in rendered["caption_text"]
