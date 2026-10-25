"""Select one licensed background track from the public R2 music catalog."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import httpx

from app.services.frame_virality import FrameInput


MAX_REMOTE_BYTES = 64 * 1024 * 1024
MOOD_ENERGY = {
    "horror": 0.38,
    "stealth": 0.44,
    "dark": 0.50,
    "funny": 0.62,
    "chiptune": 0.70,
    "electronic": 0.74,
    "epic": 0.78,
    "rock": 0.84,
    "action": 0.88,
    "hype": 0.94,
}


def _fetch_public_file(url: str) -> bytes:
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        response = client.get(url)
        response.raise_for_status()
        body = response.content
    if not body:
        raise ValueError(f"empty public music response: {url}")
    if len(body) > MAX_REMOTE_BYTES:
        raise ValueError(f"public music object exceeds {MAX_REMOTE_BYTES} bytes")
    return body


@dataclass(frozen=True)
class MusicTrack:
    id: str
    title: str
    artist: str
    key: str
    url: str
    moods: tuple[str, ...]
    duration_ms: int
    license: str
    license_url: str
    source_url: str
    credit: str

    @property
    def energy(self) -> float:
        values = [MOOD_ENERGY.get(mood, 0.65) for mood in self.moods]
        return sum(values) / len(values)

    def response(self, mood: str) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "mood": mood,
            "license": self.license,
            "license_url": self.license_url,
            "source_url": self.source_url,
            "credit": self.credit,
        }


class MusicCatalog:
    """Cache catalog metadata, then fetch only the selected MP3 from public R2."""

    def __init__(self, catalog_url: str, fetch_bytes: Callable[[str], bytes] | None = None):
        self.catalog_url = catalog_url
        self._fetch_bytes = fetch_bytes or _fetch_public_file
        self._tracks: tuple[MusicTrack, ...] | None = None
        self._lock = threading.Lock()

    def tracks(self) -> tuple[MusicTrack, ...]:
        with self._lock:
            if self._tracks is None:
                body = json.loads(self._fetch_bytes(self.catalog_url))
                parsed = tuple(
                    MusicTrack(
                        id=str(item["id"]),
                        title=str(item["title"]),
                        artist=str(item.get("artist") or "Kevin MacLeod"),
                        key=str(item["key"]),
                        url=str(item["url"]),
                        moods=tuple(str(mood).lower() for mood in item["moods"]),
                        duration_ms=int(item["duration_ms"]),
                        license=str(item["license"]),
                        license_url=str(item["license_url"]),
                        source_url=str(item["source_url"]),
                        credit=str(item["credit"]),
                    )
                    for item in body["tracks"]
                )
                if not parsed:
                    raise ValueError("public highlight music catalog is empty")
                if any(track.license != "CC BY 4.0" or not track.credit for track in parsed):
                    raise ValueError("every public music track must include its CC BY 4.0 credit")
                self._tracks = parsed
            return self._tracks

    def select(self, mood: str, energy: float, seed: str) -> MusicTrack:
        tracks = self.tracks()
        candidates = [track for track in tracks if mood in track.moods] or list(tracks)
        target = min(candidates, key=lambda track: (abs(track.energy - energy), track.id)).energy
        nearest = [track for track in candidates if abs(track.energy - target) < 0.08] or candidates
        digest = hashlib.sha256(f"{seed}:{mood}".encode()).digest()
        return sorted(nearest, key=lambda track: track.id)[int.from_bytes(digest[:4], "big") % len(nearest)]

    def download(self, track: MusicTrack, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.write_bytes(self._fetch_bytes(track.url))
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination


def _unit(values: Sequence[float]) -> tuple[float, ...]:
    vector = tuple(float(value) for value in values)
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return tuple(value / norm for value in vector)


def infer_music_profile(
    frames: Sequence[FrameInput],
    selected_ids: set,
    prompts: Sequence[Sequence[float]],
    *,
    text: str = "",
) -> tuple[str, float]:
    """Reuse transcript text and virality prompt embeddings without another model call."""
    normalized_text = " ".join(text.lower().split())
    keyword_moods = (
        ("horror", ("horror", "scary", "zombie", "monster", "terrifying")),
        ("stealth", ("stealth", "careful", "hide", "quiet", "sneak", "someone here")),
        ("dark", ("dark", "tense", "suspense", "danger", "behind you", "what was that", "do you hear")),
        ("epic", ("win", "winner", "victory", "clutch", "celebration", "defuse", "ace", "we did it", "let's go", "lets go", "nice shot")),
        ("funny", ("funny", "comedy", "hilarious", "laugh", "haha", "joke", "fail")),
        ("chiptune", ("retro", "pixel", "arcade", "8-bit", "8 bit")),
        (
            "hype",
            (
                "dance", "party", "happy", "hype", "excited", "fight", "battle", "action",
                "combat", "chase", "shoot", "boss", "enemy", "attack", "rush", "fast",
            ),
        ),
    )
    for mood, words in keyword_moods:
        if any(word in normalized_text for word in words):
            return mood, MOOD_ENERGY[mood]

    chosen = [frame for frame in frames if not selected_ids or frame.frame_id in selected_ids] or list(frames)
    if not chosen or len(prompts) < 4:
        return "hype", MOOD_ENERGY["hype"]
    centroid = _unit([sum(values) / len(chosen) for values in zip(*(frame.embedding for frame in chosen), strict=True)])
    similarities = [sum(a * b for a, b in zip(centroid, _unit(prompt), strict=True)) for prompt in prompts[:4]]
    best = max(range(len(similarities)), key=similarities.__getitem__)
    # Both action and skillful-play prompts intentionally land in the hype pool:
    # these tracks add momentum instead of merely mirroring what is on screen.
    moods = ("hype", "hype", "funny", "epic")
    spread = max(similarities) - min(similarities)
    energy = min(0.98, max(0.35, MOOD_ENERGY[moods[best]] + spread * 0.4))
    return moods[best], energy
