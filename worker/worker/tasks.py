"""Task execution: FFmpeg/ffprobe subprocess wrappers."""
from __future__ import annotations

import json
import pathlib
import subprocess

from common import ffmpeg_cmds

SUBPROCESS_TIMEOUT_S = 15 * 60


class TaskError(Exception):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=SUBPROCESS_TIMEOUT_S)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-500:]
        raise TaskError(f"{cmd[0]} exited {proc.returncode}: {tail}")
    return proc


def execute(task_type: str, src: str, work_dir: str) -> tuple[pathlib.Path, str]:
    """Run one task. Returns (output_file_path, content_type)."""
    out_dir = pathlib.Path(work_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if task_type == "transcode_1080p":
        dst = out_dir / "1080p.mp4"
        _run(ffmpeg_cmds.transcode_cmd(src, str(dst), 1080))
        return dst, "video/mp4"

    if task_type == "transcode_720p":
        dst = out_dir / "720p.mp4"
        _run(ffmpeg_cmds.transcode_cmd(src, str(dst), 720))
        return dst, "video/mp4"

    if task_type == "thumbnail":
        dst = out_dir / "thumbnail.jpg"
        _run(ffmpeg_cmds.thumbnail_cmd(src, str(dst)))
        return dst, "image/jpeg"

    if task_type == "preview_clip":
        dst = out_dir / "preview.mp4"
        _run(ffmpeg_cmds.preview_clip_cmd(src, str(dst)))
        return dst, "video/mp4"

    if task_type == "metadata":
        proc = _run(ffmpeg_cmds.ffprobe_cmd(src))
        meta = extract_metadata(json.loads(proc.stdout))
        dst = out_dir / "metadata.json"
        dst.write_text(json.dumps(meta, indent=2))
        return dst, "application/json"

    raise TaskError(f"unknown task type: {task_type}")


def extract_metadata(probe: dict) -> dict:
    """Reduce raw ffprobe output to the fields we care about (pure fn)."""
    fmt = probe.get("format", {})
    video = next((s for s in probe.get("streams", [])
                  if s.get("codec_type") == "video"), {})
    audio = next((s for s in probe.get("streams", [])
                  if s.get("codec_type") == "audio"), {})
    return {
        "duration_s": float(fmt.get("duration", 0) or 0),
        "size_bytes": int(fmt.get("size", 0) or 0),
        "bitrate": int(fmt.get("bit_rate", 0) or 0),
        "container": fmt.get("format_name"),
        "video_codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": _parse_fps(video.get("avg_frame_rate")),
        "audio_codec": audio.get("codec_name") or None,
    }


def _parse_fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "N/A"):
        return None
    try:
        num, _, den = rate.partition("/")
        return round(float(num) / float(den or 1), 3)
    except (ValueError, ZeroDivisionError):
        return None
