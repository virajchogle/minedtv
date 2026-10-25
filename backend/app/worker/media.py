"""ffmpeg / ffprobe wrappers. All blocking; call via asyncio.to_thread."""

import json
import logging
import os
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class MediaError(RuntimeError):
    pass


def executable(name: str) -> str:
    """Resolve an ffmpeg tool, allowing a project-local runtime override."""
    override = os.getenv(f"{name.upper()}_BINARY")
    return override or name


def tools_available() -> bool:
    def available(name: str) -> bool:
        candidate = executable(name)
        return Path(candidate).is_file() or shutil.which(candidate) is not None

    return available("ffmpeg") and available("ffprobe")


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
        _run([executable("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], timeout=120)
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
        executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
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
        executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t_s:.3f}", "-i", str(src),
        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out),
    ], timeout=120)
    return out


def sample_frames(src: str | Path, out_dir: Path, *, fps: float, width: int) -> list[tuple[int, Path]]:
    """One small JPEG per 1/fps seconds. Returns (t_ms, path) in time order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([
        executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-vf", f"fps={fps},scale={width}:-2", "-q:v", "5", str(out_dir / "f_%06d.jpg"),
    ])
    paths = sorted(out_dir.glob("f_*.jpg"))
    return [(round(i * 1000 / fps), p) for i, p in enumerate(paths)]


def extract_audio(src: str | Path, out: Path) -> Path:
    """Mono 16 kHz Opus: what Whisper wants, and small enough to ship to a GPU box (~10 MB/hour)."""
    _run([
        executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", str(out),
    ])
    return out


def extract_audio_range(src: str | Path, out: Path, start_ms: int, end_ms: int) -> Path:
    """Extract only a selected range as compact mono 16 kHz Opus audio."""
    if start_ms < 0 or end_ms <= start_ms:
        raise ValueError("invalid audio range")
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([
        executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start_ms / 1000:.3f}", "-i", str(src),
        "-t", f"{(end_ms - start_ms) / 1000:.3f}",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", str(out),
    ])
    return out


def render_clip(
    src: str | Path,
    out: Path,
    start_ms: int,
    end_ms: int,
    *,
    height: int = 720,
    crf: int = 23,
) -> Path:
    """Render an exact, browser-friendly MP4 range from a source video."""
    if start_ms < 0 or end_ms <= start_ms:
        raise ValueError("invalid clip range")
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([
        executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start_ms / 1000:.3f}", "-i", str(src),
        "-t", f"{(end_ms - start_ms) / 1000:.3f}",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale=-2:trunc(min({height}\\,ih)/2)*2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out),
    ])
    return out


def _ass_timestamp(ms: int) -> str:
    total_centiseconds = max(0, ms) // 10
    hours, remainder = divmod(total_centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def write_ass_captions(
    cues: list[tuple[int, int, str]],
    out: Path,
    *,
    style: str = "bold",
) -> Path:
    """Write phone-readable, centered burn-in captions for a 720x1280 canvas."""
    styles = {
        "bold": "Arial,44,&H00FFFFFF,&H00FFFFFF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,4,1,2,54,54,106,1",
        "minimal": "Arial,32,&H00FFFFFF,&H00FFFFFF,&H00101010,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,70,70,92,1",
        "gamer": "Arial,42,&H0000FF7F,&H0000FF7F,&H00100805,&H90000000,-1,0,0,0,100,100,1,0,1,4,2,2,48,48,108,1",
    }
    if style not in styles:
        raise ValueError(f"unknown caption style {style!r}")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Mobile,{styles[style]}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for start_ms, end_ms, raw_text in cues:
        cleaned = " ".join(raw_text.split()).strip()
        if not cleaned:
            continue
        wrapped = r"\N".join(textwrap.wrap(cleaned, width=32, break_long_words=False, break_on_hyphens=False))
        escaped = wrapped.replace("{", r"\{").replace("}", r"\}")
        lines.append(
            f"Dialogue: 0,{_ass_timestamp(start_ms)},{_ass_timestamp(max(end_ms, start_ms + 500))},"
            f"Mobile,,0,0,0,,{escaped}\n"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(lines), encoding="utf-8-sig")
    return out


def _ffmpeg_filter_path(path: Path) -> str:
    # FFmpeg's filter parser treats the drive colon as a separator even when
    # subprocess bypasses the shell. Forward slashes also work on Windows.
    return path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")


def render_mobile_clip(
    src: str | Path,
    out: Path,
    start_ms: int,
    end_ms: int,
    *,
    captions: Path | None = None,
    width: int = 720,
    height: int = 1280,
    crf: int = 23,
) -> Path:
    """Render a broadly compatible 9:16 MP4 without cropping landscape action.

    A blurred full-canvas copy fills the portrait background while a sharp,
    aspect-preserving copy stays centered. Optional ASS captions are burned in.
    """
    if start_ms < 0 or end_ms <= start_ms:
        raise ValueError("invalid clip range")
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise ValueError("mobile output dimensions must be positive even numbers")

    out.parent.mkdir(parents=True, exist_ok=True)
    blur_width = max(90, width // 4)
    blur_height = max(160, height // 4)
    filters = (
        f"[0:v]split=2[background][foreground];"
        f"[background]scale={blur_width}:{blur_height}:force_original_aspect_ratio=increase,"
        f"crop={blur_width}:{blur_height},boxblur=12:6,scale={width}:{height}[blurred];"
        f"[foreground]scale={width}:{height}:force_original_aspect_ratio=decrease[sharp];"
        f"[blurred][sharp]overlay=(W-w)/2:(H-h)/2,"
        "fps=30,format=yuv420p"
    )
    if captions and captions.is_file():
        filters += f",ass=filename='{_ffmpeg_filter_path(captions)}'"
    filters += "[video]"

    _run([
        executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start_ms / 1000:.3f}", "-i", str(src),
        "-t", f"{(end_ms - start_ms) / 1000:.3f}",
        "-filter_complex", filters,
        "-map", "[video]", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-profile:v", "main", "-level:v", "4.0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000",
        "-movflags", "+faststart", "-shortest", str(out),
    ])
    return out


def concatenate_mp4_segments(segments: list[Path], out: Path) -> Path:
    """Join uniformly encoded MP4 segments without another video encode."""
    if not segments:
        raise ValueError("at least one montage segment is required")
    missing = [str(path) for path in segments if not path.is_file()]
    if missing:
        raise MediaError(f"montage segments are missing: {', '.join(missing)}")

    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = out.with_suffix(".concat.txt")
    lines = []
    for segment in segments:
        # FFmpeg's concat demuxer accepts forward-slash absolute Windows paths.
        escaped = segment.resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{escaped}'\n")
    manifest.write_text("".join(lines), encoding="utf-8")
    try:
        _run([
            executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(manifest),
            "-c", "copy", "-movflags", "+faststart", str(out),
        ])
    finally:
        manifest.unlink(missing_ok=True)
    return out


def burn_ass_captions(src: Path, out: Path, captions: Path, *, crf: int = 23) -> Path:
    """Burn ASS captions into an already formatted montage, preserving its audio."""
    if not captions.is_file():
        raise MediaError("caption file is missing")
    out.parent.mkdir(parents=True, exist_ok=True)
    _run([
        executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-vf", f"ass=filename='{_ffmpeg_filter_path(captions)}'",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-profile:v", "main", "-level:v", "4.0", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", "-shortest", str(out),
    ])
    return out
