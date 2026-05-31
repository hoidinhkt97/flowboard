from pathlib import Path

import pytest

from flowboard.services.video_pipeline import merger


def test_build_concat_command_no_crossfade(tmp_path):
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    out = tmp_path / "out.mp4"
    cmd, listfile = merger.build_concat_command("ffmpeg", clips, out)
    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd and "concat" in cmd
    assert str(out) in cmd
    assert listfile is not None and listfile.exists()
    content = listfile.read_text()
    assert "a.mp4" in content and "b.mp4" in content


def test_build_xfade_command_with_audio(tmp_path):
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
    out = tmp_path / "out.mp4"
    cmd = merger.build_xfade_command("ffmpeg", clips, out,
                                     crossfade_sec=0.4, durations=[2.0, 2.0, 2.0],
                                     audio=True)
    joined = " ".join(cmd)
    assert "xfade" in joined
    assert "acrossfade" in joined
    assert str(out) in cmd


def test_build_xfade_single_clip_is_copy(tmp_path):
    clips = [tmp_path / "only.mp4"]
    out = tmp_path / "out.mp4"
    cmd = merger.build_xfade_command("ffmpeg", clips, out, crossfade_sec=0.4,
                                     durations=[2.0], audio=True)
    # one clip: nothing to crossfade -> straight copy
    assert "-c" in cmd and "copy" in cmd


@pytest.mark.asyncio
async def test_merge_writes_atomically(tmp_path, monkeypatch):
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for c in clips:
        c.write_bytes(b"\x00\x00")
    out = tmp_path / "merged.mp4"

    ran = {}
    async def fake_run(cmd):
        # simulate ffmpeg writing the *.tmp target (last cmd arg)
        Path(cmd[-1]).write_bytes(b"MERGED")
        ran["cmd"] = cmd
        return 0

    res = await merger.merge_clips(
        clips=clips, out_path=out, crossfade_sec=0.0, audio=True,
        ffmpeg_exe="ffmpeg", runner=fake_run)
    assert out.exists()
    assert out.read_bytes() == b"MERGED"
    assert res["file_size_bytes"] == 6
    # tmp cleaned
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
async def test_merge_nonzero_exit_raises(tmp_path):
    clips = [tmp_path / "a.mp4"]
    clips[0].write_bytes(b"x")
    out = tmp_path / "m.mp4"

    async def fail_run(cmd):
        return 1

    with pytest.raises(merger.MergeError):
        await merger.merge_clips(clips=clips, out_path=out, crossfade_sec=0.0,
                                 audio=True, ffmpeg_exe="ffmpeg", runner=fail_run)
