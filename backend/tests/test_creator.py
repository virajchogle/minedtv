import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import creator
from app.config import Settings
from app.main import create_app
from app.ml import audience_simulator, gemini_creator
from app.ml.audience_simulator import AudiencePanelDraft, GeminiAudienceSimulator, build_audience_simulation
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


def _persona(name, layer, hook, completion, like, comment, save, share, skip, action):
    return {
        "name": name,
        "layer": layer,
        "profile": f"A {layer} viewer",
        "interests": ["gaming"],
        "hook_score": hook,
        "completion_probability": completion,
        "like_probability": like,
        "comment_probability": comment,
        "save_probability": save,
        "share_probability": share,
        "skip_probability": skip,
        "primary_action": action,
        "reaction": f"{name}'s direct reaction",
        "suggested_comment": "That finish was clean." if action == "comment" else None,
        "what_worked": "The ending is clear.",
        "friction": "The opening could be faster.",
        "recommended_change": "Show the stakes in the first second.",
    }


def _audience_panel():
    return {
        "inferred_niche": "competitive gaming clips",
        "inferred_target_audience": "Valorant players",
        "personas": [
            _persona("Core fan", "target", 90, 0.90, 0.85, 0.65, 0.55, 0.75, 0.05, "share"),
            _persona("FPS viewer", "adjacent", 70, 0.70, 0.65, 0.40, 0.35, 0.50, 0.20, "like"),
            _persona("Casual viewer", "outsider", 40, 0.35, 0.25, 0.10, 0.08, 0.10, 0.60, "skip"),
        ],
        "consensus_strengths": ["The final play has a clear payoff."],
        "consensus_risks": ["The setup is unclear to non-players."],
        "recommended_changes": ["Add a one-line stakes overlay at the start."],
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


def test_audience_simulator_builds_three_layer_cascade(monkeypatch):
    captured = {}

    class FakeInteractions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text=json.dumps(_audience_panel()))

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.interactions = FakeInteractions()

    monkeypatch.setattr(audience_simulator.genai, "Client", FakeClient)
    settings = Settings(app_env="test", gemini_api_key="test-key", creator_persona_count=3)
    result = GeminiAudienceSimulator(settings).simulate(
        CreatorPackOut.model_validate(_content_pack()),
        "youtube",
        "competitive FPS players",
        3,
    )

    assert result.cascade_depth == "outsider"
    assert result.verdict == "promising"
    assert [layer.exposed_in_cascade for layer in result.layers] == [True, True, True]
    assert result.layers[-1].cleared_threshold is False
    assert result.metrics.action_distribution == {"like": 1, "comment": 0, "save": 0, "share": 1, "skip": 1}
    assert captured["response_format"]["schema"]["properties"]["personas"]["minItems"] == 3
    assert captured["system_instruction"]


def test_audience_simulation_endpoint(monkeypatch):
    analysis = CreatorPackOut.model_validate(_content_pack())
    simulation = build_audience_simulation(
        AudiencePanelDraft.model_validate(_audience_panel()),
        analysis,
        "instagram",
        "FPS fans",
    )

    class FakeEngine:
        def analyze(self, video_path, mime_type):
            assert video_path.read_bytes() == b"short video"
            assert mime_type == "video/mp4"
            return analysis

    class FakeSimulator:
        def simulate(self, received_analysis, platform, target_audience, persona_count):
            assert received_analysis == analysis
            assert (platform, target_audience, persona_count) == ("instagram", "FPS fans", 3)
            return simulation

    monkeypatch.setattr(creator, "get_creator_engine", lambda: FakeEngine())
    monkeypatch.setattr(creator, "get_audience_simulator", lambda: FakeSimulator())
    monkeypatch.setattr(
        creator,
        "get_settings",
        lambda: Settings(app_env="test", creator_max_upload_mb=1, creator_persona_count=3),
    )
    client = TestClient(create_app(Settings(app_env="test", api_keys=[])))

    response = client.post(
        "/creator/simulate",
        data={"platform": "instagram", "target_audience": "FPS fans", "persona_count": "3"},
        files={"video": ("clip.mp4", b"short video", "video/mp4")},
    )

    assert response.status_code == 200
    assert response.json()["persona_reviews"][0]["name"] == "Core fan"
    assert response.json()["disclaimer"].startswith("Synthetic persona feedback")
