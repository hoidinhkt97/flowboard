"""Merge per-scene clips into one mp4 via portable ffmpeg.

- crossfade_sec == 0 : concat demuxer, stream copy (instant, no re-encode).
- crossfade_sec  > 0 : filter_complex pairwise xfade (+ acrossfade for audio).
Atomic: write *.tmp then os.replace. Command builders are pure; the runner is
injected so unit tests never spawn ffmpeg.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Awaitable, Callable, Optional


class MergeError(Exception):
    pass


def get_ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def build_concat_command(ffmpeg_exe: str, clips: list[Path], out_path: Path):
    """Concat demuxer, stream copy. Returns (cmd, listfile_path)."""
    listfile = out_path.parent / f".concat-{out_path.stem}.txt"
    listfile.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    cmd = [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
           "-i", str(listfile), "-c", "copy", str(out_path)]
    return cmd, listfile


def build_xfade_command(ffmpeg_exe: str, clips: list[Path], out_path: Path, *,
                        crossfade_sec: float, durations: list[float], audio: bool):
    if len(clips) == 1:
        return [ffmpeg_exe, "-y", "-i", str(clips[0]), "-c", "copy", str(out_path)]

    cmd = [ffmpeg_exe, "-y"]
    for c in clips:
        cmd += ["-i", str(c)]

    filters = []
    # video xfade chain
    prev = "[0:v]"
    offset = 0.0
    for i in range(1, len(clips)):
        offset += durations[i - 1] - crossfade_sec
        out_label = f"[vx{i}]"
        filters.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={crossfade_sec}:"
            f"offset={offset:.3f}{out_label}")
        prev = out_label
    video_out = prev

    map_args = ["-map", video_out]
    if audio:
        aprev = "[0:a]"
        for i in range(1, len(clips)):
            out_label = f"[ax{i}]"
            filters.append(f"{aprev}[{i}:a]acrossfade=d={crossfade_sec}{out_label}")
            aprev = out_label
        map_args += ["-map", aprev]

    cmd += ["-filter_complex", ";".join(filters)] + map_args + [str(out_path)]
    return cmd


async def _default_runner(cmd: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _out, err = await proc.communicate()
    if proc.returncode != 0:
        raise MergeError(err.decode(errors="replace")[-2000:])
    return proc.returncode


async def merge_clips(
    *,
    clips: list[Path],
    out_path: Path,
    crossfade_sec: float,
    audio: bool,
    durations: Optional[list[float]] = None,
    ffmpeg_exe: Optional[str] = None,
    runner: Optional[Callable[[list[str]], Awaitable[int]]] = None,
) -> dict:
    if not clips:
        raise MergeError("no clips to merge")
    ffmpeg_exe = ffmpeg_exe or get_ffmpeg_exe()
    runner = runner or _default_runner
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(out_path.parent), suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp)
    listfile: Optional[Path] = None
    try:
        if crossfade_sec and crossfade_sec > 0:
            durations = durations or [2.0] * len(clips)
            cmd = build_xfade_command(ffmpeg_exe, clips, tmp_path,
                                      crossfade_sec=crossfade_sec,
                                      durations=durations, audio=audio)
        else:
            cmd, listfile = build_concat_command(ffmpeg_exe, clips, tmp_path)

        rc = await runner(cmd)
        if rc != 0:
            raise MergeError(f"ffmpeg exited {rc}")
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise MergeError("ffmpeg produced no output")
        os.replace(tmp_path, out_path)
        size = out_path.stat().st_size
        return {"file_size_bytes": size, "path": str(out_path)}
    finally:
        if tmp_path.exists():
            try: tmp_path.unlink()
            except OSError: pass
        if listfile and listfile.exists():
            try: listfile.unlink()
            except OSError: pass
