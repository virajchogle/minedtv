import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import creator
from app.config import Settings
from app.main import create_app
from app.ml import gemini_creator
from app.ml.gemini_creator import GeminiCreatorEngine, extract_json
from app.schemas import CreatorPackOut


def _content_pack():
    return {
        "title_options": ["One", "Two", "Three"],
        "description": "A player wins a short match.",
        "summary": "A player wins.",
        "caption": "A clean finish.",
        "youtube": {
            "title": "A Clean Finish",
            "description": "The final moments of a match.",
            "tags": ["gaming"],
            "chapters": [{"timestamp": "00:00", "label": "Match"}],
        },
        "reddit": {
            "title": "A clean finish",
            "body": "This happened at the end of my match.",
            "suggested_subreddits": ["gaming"],
        },
        "transcript": [{"timestamp": "00:01", "text": "Nice."}],
        "key_moments": [{"timestamp": "00:02", "label": "Final play"}],
        "hashtags": ["gaming"],
        "content_warnings": [],
    }


def test_extract_json_accepts_markdown_fence():
    assert extract_json(f"```json\n{json.dumps(_content_pack())}\n```")["summary"] == "A player wins."


def test_inline_analysis_returns_typed_content_pack(monkeypatch, tmp_path):
    captured = {}

    class FakeInteractions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text=json.dumps(_content_pack()))

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.interactions = FakeInteractions()

    monkeypatch.setattr(gemini_creator.genai, "Client", FakeClient)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"short video")
    settings = Settings(
        app_env="test",
        gemini_api_key="test-key",
        creator_inline_limit_mb=20,
        creator_frame_sample_fps=0.25,
    )

    result = GeminiCreatorEngine(settings).analyze(video, "video/mp4")

    assert result.summary == "A player wins."
    assert captured["client"] == {"api_key": "test-key"}
    media = captured["input"][0]
    assert media["type"] == "video"
    assert media["processing"] == {"type": "static", "fps": 0.25}
    assert captured["response_format"]["mime_type"] == "application/json"
    assert captured["response_format"]["schema"]["title"] == "CreatorPackOut"


def test_creator_endpoint_accepts_video(monkeypatch):
    class FakeEngine:
        def analyze(self, video_path, mime_type):
            assert video_path.read_bytes() == b"short video"
            assert mime_type == "video/mp4"
            return CreatorPackOut.model_validate(_content_pack())

    monkeypatch.setattr(creator, "get_creator_engine", lambda: FakeEngine())
    monkeypatch.setattr(
        creator,
        "get_settings",
        lambda: Settings(app_env="test", creator_max_upload_mb=1),
    )
    client = TestClient(create_app(Settings(app_env="test", api_keys=[])))

    response = client.post(
        "/creator/analyze",
        files={"video": ("clip.mp4", b"short video", "video/mp4")},
    )

    assert response.status_code == 200
    assert response.json()["summary"] == "A player wins."
