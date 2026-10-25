import json
import uuid

from app.services.frame_virality import FrameInput
from app.services.music_catalog import MusicCatalog, infer_music_profile


def test_catalog_selects_and_downloads_a_remote_mood_matched_track(tmp_path):
    audio = b"valid mp3 fixture"
    manifest = {
        "version": 1,
        "tracks": [
            {
                "id": "action-one",
                "title": "Action One",
                "artist": "Artist",
                "key": "music/artist/action-one.mp3",
                "url": "https://cdn.test/music/artist/action-one.mp3",
                "moods": ["action"],
                "duration_ms": 30_000,
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "source_url": "https://artist.test/action-one.mp3",
                "credit": "Action One by Artist, licensed under CC BY 4.0",
            }
        ],
    }
    payloads = {
        "https://cdn.test/music/catalog.json": json.dumps(manifest).encode(),
        "https://cdn.test/music/artist/action-one.mp3": audio,
    }

    catalog = MusicCatalog("https://cdn.test/music/catalog.json", payloads.__getitem__)
    track = catalog.select("action", 0.85, "video-1")
    path = catalog.download(track, tmp_path / "selected.mp3")

    assert track.id == "action-one"
    assert path.read_bytes() == audio
    assert track.response("action")["license"] == "CC BY 4.0"
    assert track.response("action")["credit"].startswith("Action One")


def test_music_profile_reuses_existing_virality_prompts():
    frame_id = uuid.uuid4()
    frames = [FrameInput(frame_id, 1000, [1.0, 0.0])]
    prompts = ([1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0], [0.5, 0.5])

    mood, energy = infer_music_profile(frames, {frame_id}, prompts)

    assert mood == "hype"
    assert 0.0 <= energy <= 1.0


def test_music_profile_prefers_creator_text_when_available():
    mood, energy = infer_music_profile([], set(), [], text="A tense zombie horror scene in a dark station")

    assert mood == "horror"
    assert energy == 0.38


def test_music_profile_uses_spoken_context_for_mood():
    suspense, _ = infer_music_profile([], set(), [], text="Keep quiet. There has to be someone here.")
    triumphant, energy = infer_music_profile([], set(), [], text="We did it! Let's go!")

    assert suspense == "stealth"
    assert triumphant == "epic"
    assert energy == 0.78
