"""Local, deterministic media rendering.

The pipeline is: proof artifact -> SVG -> ``ffmpeg`` (librsvg) -> PNG frames ->
``ffmpeg`` (libx264) -> MP4. Nothing is edited by hand and nothing is drawn
that the artifact does not say.

Pillow is not required. The local ``ffmpeg`` is built with librsvg, so it
rasterizes the slides directly with real font shaping, which keeps the whole
media path inside one tool that the UKSL already sanctions. ``probe_png`` and
``probe_mp4`` read the produced files back rather than trusting the encoder.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .slides import Slide, build_slides, build_thumbnail, slide_svg

__all__ = [
    "MediaError",
    "MediaResult",
    "ffmpeg_available",
    "probe_mp4",
    "probe_png",
    "render_media",
]

# -fflags/-flags +bitexact stop ffmpeg writing an encoder banner and a wall
# clock creation time into the container, so two builds of the same proof
# produce the same bytes.
_BITEXACT = ("-fflags", "+bitexact", "-flags:v", "+bitexact")


class MediaError(RuntimeError):
    """Media could not be rendered or did not read back as valid."""


@dataclass(frozen=True)
class MediaResult:
    video: Path
    thumbnail: Path
    frames: tuple[Path, ...]
    sources: tuple[Path, ...]


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _run(command: Sequence[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-8:]
        raise MediaError(
            f"{command[0]} failed ({result.returncode}) for {' '.join(command[:6])}...\n"
            + "\n".join(tail)
        )


def _rasterize(svg_path: Path, png_path: Path, width: int, height: int) -> None:
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *_BITEXACT,
            "-width",
            str(width),
            "-height",
            str(height),
            "-i",
            str(svg_path),
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            str(png_path),
        ]
    )


def _encode(concat_file: Path, video_path: Path, fps: int) -> None:
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *_BITEXACT,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-vf",
            f"fps={fps},format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(video_path),
        ]
    )


def render_media(
    *,
    artifact: Mapping[str, Any],
    receipt: Mapping[str, Any],
    out_dir: Path,
    work_dir: Path,
    fps: int = 30,
) -> MediaResult:
    """Render ``demo.mp4`` and ``thumbnail.png`` for one admitted proof."""
    if not ffmpeg_available():
        raise MediaError("ffmpeg is not on PATH; media cannot be rendered")

    work_dir.mkdir(parents=True, exist_ok=True)
    slides: list[Slide] = build_slides(artifact, receipt)

    sources: list[Path] = []
    frames: list[Path] = []
    for slide in slides:
        svg_path = work_dir / f"slide-{slide.slide_id}.svg"
        png_path = work_dir / f"slide-{slide.slide_id}.png"
        svg_path.write_text(slide_svg(slide.body), encoding="utf-8")
        _rasterize(svg_path, png_path, 1920, 1080)
        sources.append(svg_path)
        frames.append(png_path)

    concat_file = work_dir / "slides.concat"
    lines: list[str] = ["ffconcat version 1.0"]
    for slide, frame in zip(slides, frames):
        lines.append(f"file '{frame.name}'")
        lines.append(f"duration {slide.seconds:g}")
    # The concat demuxer drops the final entry's duration, so the last frame is
    # repeated to give it one.
    lines.append(f"file '{frames[-1].name}'")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    video_path = out_dir / "demo.mp4"
    _encode(concat_file, video_path, fps)

    thumb_svg = work_dir / "thumbnail.svg"
    thumb_svg.write_text(build_thumbnail(artifact, receipt), encoding="utf-8")
    thumbnail_path = out_dir / "thumbnail.png"
    _rasterize(thumb_svg, thumbnail_path, 1280, 720)
    sources.append(thumb_svg)

    probe_png(thumbnail_path)
    probe_mp4(video_path)

    return MediaResult(
        video=video_path,
        thumbnail=thumbnail_path,
        frames=tuple(frames),
        sources=tuple(sources),
    )


# --------------------------------------------------------------------------
# read the produced files back
# --------------------------------------------------------------------------

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def probe_png(path: Path) -> dict[str, Any]:
    """Parse the PNG far enough to prove it is a real, complete image.

    Header magic, IHDR geometry, a CRC-checked first chunk, and an IEND at the
    end. This is deliberately not "the file is non-empty".
    """
    data = Path(path).read_bytes()
    if len(data) < 57 or not data.startswith(_PNG_MAGIC):
        raise MediaError(f"{path} is not a PNG")
    length, chunk_type = struct.unpack(">I4s", data[8:16])
    if chunk_type != b"IHDR" or length != 13:
        raise MediaError(f"{path} has no IHDR chunk")
    body = data[16:29]
    declared_crc = struct.unpack(">I", data[29:33])[0]
    if zlib.crc32(chunk_type + body) & 0xFFFFFFFF != declared_crc:
        raise MediaError(f"{path} IHDR checksum does not match its bytes")
    width, height, depth, colour = struct.unpack(">IIBB", body[:10])
    if width == 0 or height == 0:
        raise MediaError(f"{path} declares a zero dimension")
    if not data.rstrip().endswith(b"IEND\xaeB`\x82"):
        raise MediaError(f"{path} has no IEND chunk; the image is truncated")
    return {
        "path": str(path),
        "format": "png",
        "width": width,
        "height": height,
        "bit_depth": depth,
        "colour_type": colour,
        "bytes": len(data),
    }


def probe_mp4(path: Path) -> dict[str, Any]:
    """Probe the MP4 with ffprobe, falling back to a structural box read."""
    file_path = Path(path)
    data = file_path.read_bytes()
    if len(data) < 12 or data[4:8] != b"ftyp":
        raise MediaError(f"{path} has no ftyp box; it is not an MP4")
    if b"moov" not in data[:2_000_000] and b"moov" not in data[-2_000_000:]:
        raise MediaError(f"{path} has no moov box; the container is incomplete")

    if shutil.which("ffprobe") is None:
        return {
            "path": str(file_path),
            "format": "mp4",
            "prober": "structural",
            "bytes": len(data),
        }

    result = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,nb_read_frames,avg_frame_rate:format=duration,format_name",
            "-count_frames",
            "-of",
            "default=noprint_wrappers=1",
            str(file_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise MediaError(f"ffprobe rejected {path}: {result.stderr.strip()}")

    probed: dict[str, Any] = {"path": str(file_path), "prober": "ffprobe", "bytes": len(data)}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            probed[key.strip()] = value.strip()
    if probed.get("codec_name") in (None, "", "N/A"):
        raise MediaError(f"{path} carries no decodable video stream")
    return probed
