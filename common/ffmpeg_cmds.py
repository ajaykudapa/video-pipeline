"""Pure FFmpeg/ffprobe command builders (no I/O; unit-testable)."""
from __future__ import annotations


def transcode_cmd(src: str, dst: str, height: int) -> list[str]:
    return [
        "ffmpeg", "-y", "-i", src,
        "-vf", f"scale=-2:{height}",          # -2 keeps width even for x264
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",             # web-streamable moov atom
        dst,
    ]


def thumbnail_cmd(src: str, dst: str, at_seconds: float = 1.0) -> list[str]:
    return [
        "ffmpeg", "-y",
        "-ss", str(at_seconds), "-i", src,     # -ss before -i: fast seek
        "-vframes", "1",
        "-vf", "scale=640:-2",
        dst,
    ]


def preview_clip_cmd(src: str, dst: str, duration: float = 5.0) -> list[str]:
    return [
        "ffmpeg", "-y", "-i", src,
        "-t", str(duration),
        "-vf", "scale=-2:480",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-an",                                  # previews are muted
        "-movflags", "+faststart",
        dst,
    ]


def ffprobe_cmd(src: str) -> list[str]:
    return [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        src,
    ]
