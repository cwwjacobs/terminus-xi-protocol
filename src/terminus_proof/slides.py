"""Deterministic SVG slide authoring.

Slides are built from the proof artifact and the receipts. Every value on a
slide is read out of those documents; there is no literal verdict, code, or
count written into this module. If XI rejected a check, the slide says so,
because the slide is reading the receipt.

SVG is used as the drawing surface because it is text, so a slide is
byte-reproducible and diffable, and because the local ``ffmpeg`` build
rasterizes it through librsvg with real font shaping.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from xml.sax.saxutils import escape

__all__ = ["Palette", "Slide", "build_slides", "build_thumbnail", "slide_svg"]

WIDTH = 1920
HEIGHT = 1080
THUMB_WIDTH = 1280
THUMB_HEIGHT = 720

SANS = "DejaVu Sans, Liberation Sans, Helvetica, Arial, sans-serif"
MONO = "DejaVu Sans Mono, Liberation Mono, Menlo, monospace"


@dataclass(frozen=True)
class Palette:
    background: str = "#0d1117"
    panel: str = "#161b22"
    border: str = "#30363d"
    text: str = "#e6edf3"
    muted: str = "#8b949e"
    accent: str = "#7ee787"
    admit: str = "#3fb950"
    reject: str = "#f85149"
    review: str = "#d29922"

    def verdict_color(self, verdict: str) -> str:
        return {
            "PASS": self.admit,
            "ADMIT": self.admit,
            "WARN": self.review,
            "REVIEW": self.review,
            "FAIL": self.reject,
            "REJECT": self.reject,
            "ERROR": self.reject,
        }.get(verdict, self.muted)


@dataclass(frozen=True)
class Slide:
    slide_id: str
    seconds: float
    body: str


def _text(
    x: int,
    y: int,
    content: str,
    *,
    size: int,
    fill: str,
    family: str = SANS,
    weight: str = "normal",
    anchor: str = "start",
    opacity: float = 1.0,
) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" '
        f'fill-opacity="{opacity:g}">{escape(content)}</text>'
    )


def _rect(x: int, y: int, w: int, h: int, fill: str, *, radius: int = 12, stroke: str | None = None) -> str:
    stroke_attr = f' stroke="{stroke}" stroke-width="2"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}"{stroke_attr}/>'


def _clip(content: str, width: int) -> str:
    """Hard truncate to a visible width, marking that text was dropped."""
    if len(content) <= width:
        return content
    return content[: width - 1].rstrip() + "…"


def _wrap(content: str, width: int) -> list[str]:
    if not content:
        return []
    return textwrap.wrap(content, width=width) or [content]


def _paragraph(
    x: int,
    y: int,
    content: str,
    *,
    size: int,
    fill: str,
    wrap_at: int,
    leading: int,
    family: str = SANS,
    weight: str = "normal",
    max_lines: int = 6,
) -> tuple[list[str], int]:
    parts = _wrap(content, wrap_at)
    if len(parts) > max_lines:
        parts = parts[: max_lines - 1] + [parts[max_lines - 1][: wrap_at - 1] + "…"]
    out = []
    cursor = y
    for line in parts:
        out.append(_text(x, cursor, line, size=size, fill=fill, family=family, weight=weight))
        cursor += leading
    return out, cursor


def _badge(x: int, y: int, label: str, colour: str, *, size: int = 34) -> list[str]:
    width = int(len(label) * size * 0.68) + 44
    return [
        _rect(x, y, width, size + 26, "#00000000", radius=10, stroke=colour),
        _text(x + 22, y + size + 4, label, size=size, fill=colour, family=MONO, weight="bold"),
    ]


def _chrome(palette: Palette, kicker: str, heading: str, index: str) -> list[str]:
    return [
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{palette.background}"/>',
        _rect(0, 0, WIDTH, 8, palette.accent, radius=0),
        _text(96, 128, kicker.upper(), size=30, fill=palette.accent, family=MONO, weight="bold"),
        _text(96, 208, heading, size=64, fill=palette.text, weight="bold"),
        _text(WIDTH - 96, HEIGHT - 56, index, size=26, fill=palette.muted, family=MONO, anchor="end"),
        _text(96, HEIGHT - 56, "Terminus XI Protocol", size=26, fill=palette.muted, family=MONO),
    ]


def slide_svg(body: str, *, width: int = WIDTH, height: int = HEIGHT) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{body}</svg>'
    )


# --------------------------------------------------------------------------
# slide builders
# --------------------------------------------------------------------------


def _slide_title(artifact, receipt, palette, index) -> str:
    projection = artifact["public_projection"]
    parts = [
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{palette.background}"/>',
        _rect(0, 0, WIDTH, 8, palette.accent, radius=0),
        _text(96, 200, "TERMINUS PROOF", size=32, fill=palette.accent, family=MONO, weight="bold"),
        _text(96, 330, projection["title"], size=112, fill=palette.text, weight="bold"),
    ]
    lines, cursor = _paragraph(
        96, 430, projection["subtitle"], size=48, fill=palette.muted, wrap_at=54, leading=64
    )
    parts += lines
    parts += _badge(96, cursor + 40, f"XI {receipt['admission']}", palette.verdict_color(receipt["admission"]), size=40)
    parts.append(
        _text(96, HEIGHT - 150, f"proof {artifact['demo_id']}", size=30, fill=palette.muted, family=MONO)
    )
    parts.append(
        _text(
            96,
            HEIGHT - 104,
            f"artifact sha256 {receipt['artifact_sha256'][:32]}…",
            size=30,
            fill=palette.muted,
            family=MONO,
        )
    )
    parts.append(
        _text(WIDTH - 96, HEIGHT - 56, index, size=26, fill=palette.muted, family=MONO, anchor="end")
    )
    return "".join(parts)


def _slide_claim(artifact, receipt, palette, index) -> str:
    parts = _chrome(palette, "the claim under test", "What is being claimed", index)
    lines, cursor = _paragraph(
        96, 330, artifact["claim"]["statement"], size=46, fill=palette.text, wrap_at=68, leading=64
    )
    parts += lines
    cursor += 40
    parts.append(_text(96, cursor, "SCOPE", size=28, fill=palette.accent, family=MONO, weight="bold"))
    cursor += 48
    lines, cursor = _paragraph(
        96, cursor, artifact["claim"]["scope"], size=34, fill=palette.muted, wrap_at=92, leading=48
    )
    parts += lines
    cursor += 40
    parts.append(_text(96, cursor, "NOT CLAIMED", size=28, fill=palette.reject, family=MONO, weight="bold"))
    cursor += 48
    for item in artifact["claim"]["not_claimed"][:3]:
        parts.append(_text(96, cursor, f"· {_clip(item, 88)}", size=32, fill=palette.muted))
        cursor += 44
    return "".join(parts)


def _slide_contract(artifact, receipt, palette, index) -> str:
    projection = artifact["public_projection"]
    contract = artifact["contract_sets"]["arm"]
    parts = _chrome(palette, projection["labels"]["contract"], "Frozen contract set", index)
    parts.append(
        _text(
            96,
            268,
            f"{contract['id']} v{contract['version']}  sha256 {contract['sha256'][:16]}",
            size=30,
            fill=palette.muted,
            family=MONO,
        )
    )
    cursor = 340
    for check in projection["contract_checks"]:
        parts.append(_rect(96, cursor - 44, WIDTH - 192, 96, palette.panel, stroke=palette.border))
        parts.append(
            _text(132, cursor, check["check_id"], size=32, fill=palette.accent, family=MONO, weight="bold")
        )
        parts.append(_text(132, cursor + 44, _clip(check["title"], 96), size=30, fill=palette.text))
        cursor += 124
    return "".join(parts)


def _arm_panel(arm, palette, x, y, w, h) -> list[str]:
    colour = palette.verdict_color(arm["admission"])
    parts = [
        _rect(x, y, w, h, palette.panel, stroke=palette.border),
        _text(x + 40, y + 64, _clip(arm["label"], 34), size=36, fill=palette.text, weight="bold"),
        _text(
            x + 40,
            y + 112,
            f"capability_enabled = {str(arm['capability_enabled']).lower()}",
            size=26,
            fill=palette.muted,
            family=MONO,
        ),
    ]
    parts += _badge(x + 40, y + 142, arm["admission"], colour, size=36)
    cursor = y + 262
    parts.append(
        _text(x + 40, cursor, f"claims: {arm['claim_count']}", size=30, fill=palette.text, family=MONO)
    )
    cursor += 48
    parts.append(
        _text(
            x + 40,
            cursor,
            f"blocking codes: {len(arm['blocking_codes'])}",
            size=30,
            fill=colour,
            family=MONO,
        )
    )
    cursor += 44
    codes = list(arm["blocking_codes"][:5]) or ["none"]
    for code in codes:
        parts.append(_text(x + 62, cursor, f"· {code}", size=26, fill=colour, family=MONO))
        cursor += 38
    cursor += 38 * (5 - len(codes)) + 20
    parts.append(_text(x + 40, cursor, "FIRST CLAIM", size=24, fill=palette.muted, family=MONO))
    cursor += 40
    claim_lines = _wrap(arm["sample_claim"] or "(no claim produced)", 44)
    if len(claim_lines) > 3:
        claim_lines = claim_lines[:2] + [claim_lines[2][:42].rstrip() + "…"]
    for line in claim_lines:
        parts.append(_text(x + 40, cursor, line, size=28, fill=palette.text))
        cursor += 38
    return parts


def _slide_arms(artifact, receipt, palette, index) -> str:
    projection = artifact["public_projection"]
    parts = _chrome(palette, "same fixture, same model, same tools", "Two runs, one difference", index)
    panel_w = (WIDTH - 192 - 48) // 2
    panel_h = 716
    parts += _arm_panel(projection["arms"]["baseline"], palette, 96, 272, panel_w, panel_h)
    parts += _arm_panel(
        projection["arms"]["augmented"], palette, 96 + panel_w + 48, 272, panel_w, panel_h
    )
    return "".join(parts)


def _slide_changed_variable(artifact, receipt, palette, index) -> str:
    projection = artifact["public_projection"]
    changed = projection["changed_variable"]
    parity = [
        result
        for result in receipt["check_results"]
        if result["check_id"].startswith("proof.parity.") or result["check_id"] == "proof.spec.faithful"
    ]
    parts = _chrome(palette, "the controlled variable", "One variable changed", index)
    parts.append(_rect(96, 300, WIDTH - 192, 200, palette.panel, stroke=palette.border))
    parts.append(
        _text(136, 372, changed["name"], size=44, fill=palette.accent, family=MONO, weight="bold")
    )
    parts.append(
        _text(
            136,
            446,
            f"{changed['baseline']}   →   {changed['augmented']}",
            size=44,
            fill=palette.text,
            family=MONO,
        )
    )
    cursor = 580
    parts.append(
        _text(96, cursor, "HELD IDENTICAL, AND CHECKED", size=28, fill=palette.muted, family=MONO, weight="bold")
    )
    cursor += 64
    for result in parity:
        colour = palette.verdict_color(result["verdict"])
        parts.append(_text(96, cursor, result["verdict"], size=32, fill=colour, family=MONO, weight="bold"))
        parts.append(_text(240, cursor, result["check_id"], size=32, fill=palette.text, family=MONO))
        message = result["findings"][0]["message"] if result["findings"] else ""
        parts.append(_text(760, cursor, _clip(message, 68), size=28, fill=palette.muted))
        cursor += 56
    return "".join(parts)


def _slide_verdict(artifact, receipt, palette, index) -> str:
    projection = artifact["public_projection"]
    parts = _chrome(palette, projection["labels"]["verdict"], "XI decision", index)
    colour = palette.verdict_color(receipt["admission"])
    parts.append(
        _text(
            96,
            268,
            f"boundary {receipt['boundary_id']}   policy {artifact['policies']['package']['id']}",
            size=28,
            fill=palette.muted,
            family=MONO,
        )
    )
    cursor = 330
    for result in receipt["check_results"]:
        row_colour = palette.verdict_color(result["verdict"])
        parts.append(
            _text(96, cursor, result["verdict"], size=30, fill=row_colour, family=MONO, weight="bold")
        )
        parts.append(_text(240, cursor, result["check_id"], size=30, fill=palette.text, family=MONO))
        codes = sorted({item["code"] for item in result["findings"]}) or ["-"]
        parts.append(_text(880, cursor, _clip(", ".join(codes), 64), size=26, fill=palette.muted, family=MONO))
        cursor += 48
    parts += _badge(96, cursor + 30, f"ADMISSION {receipt['admission']}", colour, size=40)
    blocking = receipt["admission_rationale"]["blocking_codes"]
    parts.append(
        _text(
            700,
            cursor + 78,
            f"blocking codes: {', '.join(blocking) if blocking else 'none'}",
            size=30,
            fill=colour,
            family=MONO,
        )
    )
    return "".join(parts)


def _slide_receipt(artifact, receipt, palette, index) -> str:
    projection = artifact["public_projection"]
    provenance = receipt["provenance"]
    parts = _chrome(palette, projection["labels"]["receipt"], "Receipt and provenance", index)
    rows = [
        ("run_id", provenance["run_id"]),
        ("artifact sha256", receipt["artifact_sha256"]),
        ("stable core sha256", receipt["stable_core_sha256"]),
        ("receipt sha256", receipt["receipt_sha256"]),
        ("contract set sha256", receipt["contract_set_sha256"]),
        ("policy sha256", receipt["policy_sha256"] or "-"),
        ("protocol", receipt["protocol_version"]),
        ("runtime", receipt["runtime_version"]),
        ("model", f"{provenance['model']['provider']}/{provenance['model']['model_id']}"),
        ("fixture", provenance["fixture"]["fixture_id"]),
        ("redaction policy", f"{artifact['redaction']['policy_id']} v{artifact['redaction']['policy_version']}"),
    ]
    cursor = 300
    for label, value in rows:
        parts.append(_text(96, cursor, label, size=28, fill=palette.muted, family=MONO))
        parts.append(_text(640, cursor, _clip(str(value), 64), size=28, fill=palette.text, family=MONO))
        cursor += 52
    parts.append(
        _text(
            96,
            cursor + 40,
            "A digest proves identity of the bytes it covers. It does not prove truth.",
            size=30,
            fill=palette.muted,
        )
    )
    return "".join(parts)


_BUILDERS = (
    ("title", 5.0, _slide_title),
    ("claim", 7.0, _slide_claim),
    ("contract", 6.0, _slide_contract),
    ("arms", 8.0, _slide_arms),
    ("changed-variable", 7.0, _slide_changed_variable),
    ("verdict", 8.0, _slide_verdict),
    ("receipt", 7.0, _slide_receipt),
)


def build_slides(
    artifact: Mapping[str, Any], receipt: Mapping[str, Any], palette: Palette | None = None
) -> list[Slide]:
    """Build every slide for one admitted proof, in order."""
    resolved = palette or Palette(accent=artifact["public_projection"].get("accent", "#7ee787"))
    total = len(_BUILDERS)
    slides: list[Slide] = []
    for position, (slide_id, seconds, builder) in enumerate(_BUILDERS, start=1):
        index = f"{position}/{total}"
        slides.append(
            Slide(
                slide_id=f"{position:02d}-{slide_id}",
                seconds=seconds,
                body=builder(artifact, receipt, resolved, index),
            )
        )
    return slides


def build_thumbnail(
    artifact: Mapping[str, Any], receipt: Mapping[str, Any], palette: Palette | None = None
) -> str:
    """A single still that states the result without motion."""
    resolved = palette or Palette(accent=artifact["public_projection"].get("accent", "#7ee787"))
    projection = artifact["public_projection"]
    baseline = projection["arms"]["baseline"]
    augmented = projection["arms"]["augmented"]
    colour = resolved.verdict_color(receipt["admission"])

    parts = [
        f'<rect width="{THUMB_WIDTH}" height="{THUMB_HEIGHT}" fill="{resolved.background}"/>',
        f'<rect x="0" y="0" width="{THUMB_WIDTH}" height="6" fill="{resolved.accent}"/>',
        _text(72, 116, "TERMINUS PROOF", size=24, fill=resolved.accent, family=MONO, weight="bold"),
        _text(72, 196, projection["title"], size=76, fill=resolved.text, weight="bold"),
    ]
    lines, cursor = _paragraph(
        72, 258, projection["subtitle"], size=32, fill=resolved.muted, wrap_at=52, leading=44, max_lines=2
    )
    parts += lines

    panel_w = (THUMB_WIDTH - 144 - 32) // 2
    top = 340
    for offset, arm in ((0, baseline), (panel_w + 32, augmented)):
        arm_colour = resolved.verdict_color(arm["admission"])
        x = 72 + offset
        parts.append(_rect(x, top, panel_w, 200, resolved.panel, stroke=resolved.border))
        parts.append(
            _text(x + 28, top + 52, _clip(arm["label"], 34), size=26, fill=resolved.muted)
        )
        parts.append(
            _text(x + 28, top + 120, arm["admission"], size=54, fill=arm_colour, family=MONO, weight="bold")
        )
        parts.append(
            _text(
                x + 28,
                top + 166,
                f"{len(arm['blocking_codes'])} blocking codes / {arm['claim_count']} claims",
                size=24,
                fill=resolved.muted,
                family=MONO,
            )
        )

    parts += _badge(72, top + 236, f"XI {receipt['admission']}", colour, size=32)
    parts.append(
        _text(
            THUMB_WIDTH - 72,
            THUMB_HEIGHT - 48,
            f"sha256 {receipt['artifact_sha256'][:24]}…",
            size=22,
            fill=resolved.muted,
            family=MONO,
            anchor="end",
        )
    )
    return slide_svg("".join(parts), width=THUMB_WIDTH, height=THUMB_HEIGHT)
