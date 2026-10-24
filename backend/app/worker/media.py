"""ffmpeg / ffprobe wrappers. All blocking; call via asyncio.to_thread."""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class MediaError(RuntimeError):
    pass


def _run(args: list[str], timeout: int = 3600) -> str:
    log.debug("exec", extra={"cmd": " ".join(args)})
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise MediaError(f"{args[0]} exited {proc.returncode}: {tail}")
    return proc.stdout


@dataclass
class ProbeResult:
    duration_ms: int
    width: int
    height: int
    fps: float
    has_audio: bool


def _parse_rate(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    num, _, den = rate.partition("/")
    return float(num) / float(den or 1)


def probe(path: str | Path) -> ProbeResult:
    out = json.loads(
        _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], timeout=120)
    )
    streams = out.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError("no video stream found")
    duration = float(out.get("format", {}).get("duration") or video.get("duration") or 0)
    if duration <= 0:
        raise MediaError("could not determine duration")
    return ProbeResult(
        duration_ms=int(duration * 1000),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=round(_parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate")), 3),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


@dataclass
class HlsSegment:
    idx: int
    path: Path
    start_ms: int
    duration_ms: int


def transcode_hls(
    src: str | Path, out_dir: Path, *, height: int, crf: int, segment_s: int, has_audio: bool
) -> list[HlsSegment]:
    """Transcode to <=height p H.264/AAC and cut into segment_s-second HLS segments on keyframes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-map", "0:v:0",
    ]
    if has_audio:
        args += ["-map", "0:a:0"]
    args += [
        # Never upscale; keep dimensions even for H.264.
        "-vf", f"scale=-2:trunc(min({height}\\,ih)/2)*2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        # Keyframe exactly every segment_s seconds so every segment starts on one.
        "-force_key_frames", f"expr:gte(t,n_forced*{segment_s})", "-sc_threshold", "0",
    ]
    if has_audio:
        args += ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    args += [
        "-f", "hls", "-hls_time", str(segment_s), "-hls_playlist_type", "vod",
        "-hls_segment_filename", str(out_dir / "seg_%05d.ts"),
        str(out_dir / "index.m3u8"),
    ]
    _run(args)
    return parse_hls_index(out_dir / "index.m3u8")


def parse_hls_index(index: Path) -> list[HlsSegment]:
    segments: list[HlsSegment] = []
    start = 0
    duration_ms = None
    for line in index.read_text().splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            duration_ms = round(float(line[len("#EXTINF:"):].split(",")[0]) * 1000)
        elif line and not line.startswith("#") and duration_ms is not None:
            segments.append(HlsSegment(len(segments), index.parent / line, start, duration_ms))
            start += duration_ms
            duration_ms = None
    if not segments:
        raise MediaError("ffmpeg produced no HLS segments")
    return segments


def extract_image(src: str | Path, out: Path, t_s: float, width: int) -> Path:
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t_s:.3f}", "-i", str(src),
        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out),
    ], timeout=120)
    return out


def sample_frames(src: str | Path, out_dir: Path, *, fps: float, width: int) -> list[tuple[int, Path]]:
    """One small JPEG per 1/fps seconds. Returns (t_ms, path) in time order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-vf", f"fps={fps},scale={width}:-2", "-q:v", "5", str(out_dir / "f_%06d.jpg"),
    ])
    paths = sorted(out_dir.glob("f_*.jpg"))
    return [(round(i * 1000 / fps), p) for i, p in enumerate(paths)]


def extract_audio(src: str | Path, out: Path) -> Path:
    """Mono 16 kHz Opus: what Whisper wants, and small enough to ship to a GPU box (~10 MB/hour)."""
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", str(out),
    ])
    return out
