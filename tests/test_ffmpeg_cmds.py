from common import ffmpeg_cmds


def test_transcode_cmd():
    cmd = ffmpeg_cmds.transcode_cmd("in.mp4", "out.mp4", 720)
    assert cmd[0] == "ffmpeg"
    assert "scale=-2:720" in cmd          # width stays even for x264
    assert "+faststart" in cmd            # web-streamable
    assert cmd[-1] == "out.mp4"


def test_thumbnail_seeks_before_input_for_speed():
    cmd = ffmpeg_cmds.thumbnail_cmd("in.mp4", "thumb.jpg", at_seconds=2.5)
    assert cmd.index("-ss") < cmd.index("-i")
    assert "-vframes" in cmd


def test_preview_clip_is_muted_and_short():
    cmd = ffmpeg_cmds.preview_clip_cmd("in.mp4", "prev.mp4", duration=5.0)
    assert "-an" in cmd
    assert cmd[cmd.index("-t") + 1] == "5.0"


def test_ffprobe_outputs_json():
    cmd = ffmpeg_cmds.ffprobe_cmd("in.mp4")
    assert cmd[0] == "ffprobe"
    assert "json" in cmd
