import pytest

from app.config import Settings
from app.schemas import CreatorPackOut
from app.worker.creator_pack import analyze_with_fallback, is_capacity_error

PACK = {
    "title_options": ["a", "b", "c"], "description": "d", "summary": "s", "caption": "c",
    "youtube": {"title": "t", "description": "d", "tags": ["x"], "chapters": [{"timestamp": "00:00", "label": "start"}]},
    "reddit": {"title": "t", "body": "b", "suggested_subreddits": ["valorant"]},
    "transcript": [], "key_moments": [], "hashtags": ["valorant"], "content_warnings": [],
}


class Busy(Exception):
    pass


def engine_factory(behaviour: dict[str, Exception | None], calls: list[str]):
    class FakeEngine:
        def __init__(self, settings):
            self.model = settings.gemini_model

        def analyze(self, path, mime):
            calls.append(self.model)
            err = behaviour.get(self.model)
            if err:
                raise err
            return CreatorPackOut.model_validate(PACK)

    return FakeEngine


def settings(**kw):
    return Settings(gemini_api_key="k", gemini_model="m1", gemini_fallback_models=["m2", "m3"], **kw)


def test_capacity_errors_detected_through_cause_chain():
    try:
        try:
            raise Busy("Error code: 503 - currently experiencing high demand")
        except Busy as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        assert is_capacity_error(outer)
    assert is_capacity_error(Exception("429 RESOURCE_EXHAUSTED"))
    assert not is_capacity_error(ValueError("invalid JSON"))


def test_falls_back_to_next_model_when_busy(tmp_path):
    calls = []
    pack, model = analyze_with_fallback(tmp_path / "v.mp4", settings(),
                                        engine_factory({"m1": Busy("503 high demand")}, calls))
    assert model == "m2" and calls == ["m1", "m2"] and pack.hashtags == ["valorant"]


def test_non_capacity_errors_are_not_retried(tmp_path):
    calls = []
    with pytest.raises(ValueError):
        analyze_with_fallback(tmp_path / "v.mp4", settings(), engine_factory({"m1": ValueError("bad pack")}, calls))
    assert calls == ["m1"]


def test_all_models_busy(tmp_path):
    calls = []
    busy = Busy("503")
    with pytest.raises(RuntimeError, match="all Gemini models busy"):
        analyze_with_fallback(tmp_path / "v.mp4", settings(), engine_factory({"m1": busy, "m2": busy, "m3": busy}, calls))
    assert calls == ["m1", "m2", "m3"]
