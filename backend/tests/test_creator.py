import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import creator
from app.config import Settings
from app.main import create_app
from app.ml import audience_simulator, gemini_captions, gemini_creator
from app.ml.audience_simulator import AudiencePanelDraft, GeminiAudienceSimulator, build_audience_simulation
from app.ml.gemini_captions import GeminiCaptionEngine
from app.ml.gemini_creator import GeminiCreatorEngine, extract_json
from app.schemas import CreatorPackOut, VideoViralityEvidenceOut


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


def _audience_wire_panel():
    panel = _audience_panel()
    return {
        "niche": panel["inferred_niche"],
        "audience": panel["inferred_target_audience"],
        "personas": [
            {
                "name": persona["name"],
                "profile": persona["profile"],
                "interests": ", ".join(persona["interests"]),
                "hook": persona["hook_score"],
                "completion": persona["completion_probability"],
                "like": persona["like_probability"],
                "comment": persona["comment_probability"],
                "save": persona["save_probability"],
                "share": persona["share_probability"],
                "skip": persona["skip_probability"],
                "action": persona["primary_action"],
                "reaction": persona["reaction"],
                "suggested_comment": persona["suggested_comment"] or "",
                "worked": persona["what_worked"],
                "friction": persona["friction"],
                "change": persona["recommended_change"],
            }
            for persona in panel["personas"]
        ],
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
    assert captured["generation_config"] == {
        "thinking_level": "minimal",
        "max_output_tokens": 8192,
    }
    assert captured["timeout"] == 90


def test_focused_caption_engine_returns_timed_cues(monkeypatch, tmp_path):
    captured = {}

    class FakeInteractions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text=json.dumps({
                "cues": [
                    {"start_ms": 100, "end_ms": 1400, "text": "Plant the defuser!"},
                    {"start_ms": 1500, "end_ms": 2600, "text": "[Gunfire]"},
                ]
            }))

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.interactions = FakeInteractions()

    monkeypatch.setattr(gemini_captions.genai, "Client", FakeClient)
    audio = tmp_path / "selected.opus"
    audio.write_bytes(b"short selected audio")
    settings = Settings(app_env="test", gemini_api_key="test-key")

    cues = GeminiCaptionEngine(settings).transcribe_audio(audio)

    assert [(cue.start_ms, cue.end_ms, cue.text) for cue in cues] == [
        (100, 1400, "Plant the defuser!"),
        (1500, 2600, "[Gunfire]"),
    ]
    assert captured["client"] == {"api_key": "test-key"}
    assert captured["generation_config"] == {"thinking_level": "minimal", "max_output_tokens": 2048}
    assert captured["input"][0]["type"] == "audio"
    assert captured["input"][0]["mime_type"] == "audio/opus"
    assert "processing" not in captured["input"][0]


def test_focused_caption_engine_normalizes_seconds_mislabeled_as_milliseconds(monkeypatch, tmp_path):
    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(output_text=json.dumps({
                "cues": [
                    {"start_ms": 0, "end_ms": 2, "text": "There has to be someone here."},
                    {"start_ms": 8, "end_ms": 10, "text": "Not good."},
                    {"start_ms": 30, "end_ms": 31, "text": "[Groaning]"},
                ]
            }))

    class FakeClient:
        def __init__(self, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr(gemini_captions.genai, "Client", FakeClient)
    audio = tmp_path / "selected.opus"
    audio.write_bytes(b"audio")

    cues = GeminiCaptionEngine(Settings(app_env="test", gemini_api_key="test-key")).transcribe_audio(
        audio,
        duration_ms=32_000,
    )

    assert [(cue.start_ms, cue.end_ms) for cue in cues] == [
        (0, 2000),
        (8000, 10_000),
        (30_000, 31_000),
    ]


def test_creator_endpoint_accepts_video(monkeypatch):
    class FakeEngine:
        def analyze(self, video_path, mime_type):
            assert video_path.read_bytes() == b"short video"
            assert mime_type == "video/mp4"
            return CreatorPackOut.model_validate(_content_pack())

    monkeypatch.setattr(creator, "get_creator_engine", lambda: FakeEngine())
    monkeypatch.setattr(
        creator,
        "get_audience_simulator",
        lambda: (_ for _ in ()).throw(AssertionError("analyze must not initialize personas")),
    )
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
    calls = 0

    class FakeInteractions:
        closed = False

        def create(self, **kwargs):
            nonlocal calls
            calls += 1
            assert not self.closed, "Gemini client was finalized before the request"
            captured.update(kwargs)
            return SimpleNamespace(output_text=json.dumps(_audience_wire_panel()))

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.interactions = FakeInteractions()

        def __del__(self):
            self.interactions.closed = True

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
    assert calls == 1
    persona_schema = captured["response_format"]["schema"]["properties"]["personas"]
    assert "minItems" not in persona_schema
    assert "maxItems" not in persona_schema
    assert "$defs" not in captured["response_format"]["schema"]
    assert captured["system_instruction"]
    assert captured["generation_config"] == {
        "thinking_level": "minimal",
        "max_output_tokens": 1150,
    }
    request_data = json.loads(captured["input"].split("INPUT DATA:\n", 1)[1])
    assert request_data["platform"] == "youtube"
    assert "youtube" not in request_data["video_content"]
    assert "reddit" not in request_data["video_content"]


def test_audience_simulator_blends_frame_evidence_without_extra_model_calls(monkeypatch):
    captured = {}
    calls = 0

    class FakeInteractions:
        def create(self, **kwargs):
            nonlocal calls
            calls += 1
            captured.update(kwargs)
            return SimpleNamespace(output_text=json.dumps(_audience_wire_panel()))

    class FakeClient:
        def __init__(self, **kwargs):
            self.interactions = FakeInteractions()

    evidence = VideoViralityEvidenceOut(
        algorithm_version="persona-frame-virality-test",
        duration_ms=10_000,
        frames_analyzed=5,
        frame_score=20,
        peak_score=50,
        hook_score=40,
        sustained_score=30,
        coverage=0.2,
        moments=[],
    )
    monkeypatch.setattr(audience_simulator.genai, "Client", FakeClient)
    simulator = GeminiAudienceSimulator(
        Settings(
            app_env="test",
            gemini_api_key="test-key",
            creator_persona_count=3,
            creator_virality_frame_weight=0.25,
        )
    )
    result = simulator.simulate(
        CreatorPackOut.model_validate(_content_pack()),
        "youtube",
        "competitive FPS players",
        3,
        evidence,
    )

    assert calls == 1
    assert result.video_evidence == evidence
    assert result.persona_score is not None
    assert result.virality_score == round(result.persona_score * 0.75 + 20 * 0.25, 1)
    assert "persona-frame-virality-test" in result.scoring_version
    request_data = json.loads(captured["input"].split("INPUT DATA:\n", 1)[1])
    assert request_data["frame_evidence"]["frames_analyzed"] == 5


def test_persona_score_does_not_double_penalize_stopped_cascade():
    analysis = CreatorPackOut.model_validate(_content_pack())
    result = build_audience_simulation(
        AudiencePanelDraft.model_validate(_audience_panel()),
        analysis,
        "general",
        None,
    )

    expected = round(
        0.55 * result.layers[0].score
        + 0.30 * result.layers[1].score
        + 0.15 * result.layers[2].score,
        1,
    )
    assert result.persona_score == expected
    assert result.scoring_version == "persona-cascade-v3"


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


def test_frame_aware_video_virality_endpoint_reuses_one_upload(monkeypatch):
    analysis = CreatorPackOut.model_validate(_content_pack())
    evidence = VideoViralityEvidenceOut(
        algorithm_version="persona-frame-virality-test",
        duration_ms=10_000,
        frames_analyzed=5,
        frame_score=72,
        peak_score=90,
        hook_score=75,
        sustained_score=68,
        coverage=0.4,
        moments=[],
    )
    simulation = build_audience_simulation(
        AudiencePanelDraft.model_validate(_audience_panel()),
        analysis,
        "general",
        "FPS fans",
        evidence,
    )
    calls = {"analysis": 0, "prepare": 0, "evidence": 0, "persona": 0}

    class FakeEngine:
        def analyze(self, video_path, mime_type):
            calls["analysis"] += 1
            assert video_path.read_bytes() == b"short video"
            return analysis

    class FakeEvidenceEngine:
        def prepare(self, video_path):
            calls["prepare"] += 1
            assert video_path.read_bytes() == b"short video"
            return "prepared-frames"

        def evidence(self, prepared, received_analysis):
            calls["evidence"] += 1
            assert prepared == "prepared-frames"
            assert received_analysis == analysis
            return evidence

    class FakeSimulator:
        def simulate(self, received_analysis, platform, target_audience, persona_count, received_evidence):
            calls["persona"] += 1
            assert received_analysis == analysis
            assert received_evidence == evidence
            assert (platform, target_audience, persona_count) == ("general", "FPS fans", 3)
            return simulation

    monkeypatch.setattr(creator.media, "tools_available", lambda: True)
    monkeypatch.setattr(creator, "get_creator_engine", lambda: FakeEngine())
    monkeypatch.setattr(creator, "get_video_persona_virality_engine", lambda: FakeEvidenceEngine())
    monkeypatch.setattr(creator, "get_audience_simulator", lambda: FakeSimulator())
    monkeypatch.setattr(
        creator,
        "get_settings",
        lambda: Settings(app_env="test", creator_max_upload_mb=1, creator_persona_count=3),
    )
    client = TestClient(create_app(Settings(app_env="test", api_keys=[])))

    response = client.post(
        "/creator/virality",
        data={"target_audience": "FPS fans", "persona_count": "3"},
        files={"video": ("clip.mp4", b"short video", "video/mp4")},
    )

    assert response.status_code == 200
    assert calls == {"analysis": 1, "prepare": 1, "evidence": 1, "persona": 1}
    assert response.json()["video_evidence"]["frames_analyzed"] == 5
    assert response.json()["persona_score"] == simulation.persona_score


def test_audience_simulation_reuses_existing_analysis(monkeypatch):
    analysis = CreatorPackOut.model_validate(_content_pack())
    simulation = build_audience_simulation(
        AudiencePanelDraft.model_validate(_audience_panel()),
        analysis,
        "youtube",
        "FPS fans",
    )

    class FakeSimulator:
        def simulate(self, received_analysis, platform, target_audience, persona_count):
            assert received_analysis == analysis
            assert (platform, target_audience, persona_count) == ("general", "FPS fans", 3)
            return simulation

    monkeypatch.setattr(creator, "get_audience_simulator", lambda: FakeSimulator())
    monkeypatch.setattr(
        creator,
        "get_settings",
        lambda: Settings(app_env="test", creator_persona_count=3),
    )
    client = TestClient(create_app(Settings(app_env="test", api_keys=[])))

    response = client.post(
        "/creator/simulate-analysis",
        json={
            "analysis": _content_pack(),
            "target_audience": "FPS fans",
            "persona_count": 3,
        },
    )

    assert response.status_code == 200
    assert response.json()["analysis"] == _content_pack()
