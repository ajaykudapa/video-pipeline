from worker.tasks import _parse_fps, extract_metadata

SAMPLE_PROBE = {
    "format": {"duration": "12.5", "size": "1048576",
               "bit_rate": "671088", "format_name": "mov,mp4,m4a"},
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1920,
         "height": 1080, "avg_frame_rate": "30000/1001"},
        {"codec_type": "audio", "codec_name": "aac"},
    ],
}


def test_extract_metadata():
    m = extract_metadata(SAMPLE_PROBE)
    assert m["duration_s"] == 12.5
    assert m["width"] == 1920 and m["height"] == 1080
    assert m["video_codec"] == "h264"
    assert m["audio_codec"] == "aac"
    assert m["fps"] == 29.97


def test_extract_metadata_handles_missing_streams():
    m = extract_metadata({"format": {}, "streams": []})
    assert m["duration_s"] == 0.0
    assert m["video_codec"] is None
    assert m["audio_codec"] is None


def test_parse_fps_edge_cases():
    assert _parse_fps("30/1") == 30.0
    assert _parse_fps("0/0") is None
    assert _parse_fps(None) is None
    assert _parse_fps("garbage") is None
