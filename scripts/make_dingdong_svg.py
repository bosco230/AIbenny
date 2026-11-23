"""Generate the original 叮當 character: a refined pearl-white robot.

Writes characters/dingdong/faces/<expression>/000.svg (resting mouth) and
001-003.svg (speaking mouth, small -> wide), plus faces/blink.svg and
faces/smile_blink.svg.

Expressions: neutral, smile, happy, sad, angry, surprised, worried, thinking.

Design: glossy pearl shell with gradient shading, dark glass visor whose
eyes and mouth glow, teal ear pods / chest light / cuffs, floating hands and
a metallic golden bell on the antenna (the "叮"). Deliberately original.

Usage:  python -I scripts/make_dingdong_svg.py
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "characters" / "dingdong" / "faces"

EXPRESSIONS = ("neutral", "smile", "happy", "sad", "angry", "surprised", "worried", "thinking")

CYAN = "#6FF2FF"
BLUE = "#8FC8FF"
RED = "#FF8A8A"
PINK = "#FF9BB3"
GOLD = "#FFD36A"


def glow_color(expression: str) -> str:
    return {"sad": BLUE, "angry": RED}.get(expression, CYAN)


DEFS = """
<defs>
  <radialGradient id="shell" cx="0.36" cy="0.28" r="0.8">
    <stop offset="0" stop-color="#FFFFFF"/>
    <stop offset="0.5" stop-color="#EEF3F7"/>
    <stop offset="1" stop-color="#C4D2DD"/>
  </radialGradient>
  <linearGradient id="teal" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#5BE6D8"/>
    <stop offset="1" stop-color="#128C82"/>
  </linearGradient>
  <radialGradient id="visor" cx="0.42" cy="0.3" r="0.85">
    <stop offset="0" stop-color="#2C4A66"/>
    <stop offset="0.55" stop-color="#0F1C2C"/>
    <stop offset="1" stop-color="#060B13"/>
  </radialGradient>
  <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#FFF1B0"/>
    <stop offset="0.45" stop-color="#F2BE45"/>
    <stop offset="1" stop-color="#B57A12"/>
  </linearGradient>
  <linearGradient id="metal" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#8A9DAD"/>
    <stop offset="0.5" stop-color="#D6E0E8"/>
    <stop offset="1" stop-color="#7E91A1"/>
  </linearGradient>
  <radialGradient id="ground" cx="0.5" cy="0.5" r="0.5">
    <stop offset="0" stop-color="#000" stop-opacity="0.28"/>
    <stop offset="1" stop-color="#000" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="drop" cx="0.4" cy="0.35" r="0.7">
    <stop offset="0" stop-color="#E6F6FF"/>
    <stop offset="1" stop-color="#7CC6F2"/>
  </radialGradient>
  <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur stdDeviation="3.2" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="soft" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur stdDeviation="5"/>
  </filter>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">
    <feDropShadow dx="0" dy="6" stdDeviation="6" flood-color="#1B2B38" flood-opacity="0.22"/>
  </filter>
</defs>"""


def chest(expression: str) -> str:
    if expression in ("smile", "happy"):
        core = (
            f'<path d="M200 362 Q186 352 189 343 Q193 336 200 343 Q207 336 211 343 Q214 352 200 362 Z" '
            f'fill="{PINK}" filter="url(#glow)"/>'
        )
    else:
        core = f'<circle cx="200" cy="350" r="9" fill="{glow_color(expression)}" filter="url(#glow)"/>'
    return (
        '<circle cx="200" cy="350" r="24" fill="#0F1C2C"/>'
        '<circle cx="200" cy="350" r="24" fill="none" stroke="url(#teal)" stroke-width="6"/>'
        + core
    )


def body(expression: str) -> str:
    return f"""
  <ellipse cx="200" cy="452" rx="96" ry="13" fill="url(#ground)"/>
  <!-- torso -->
  <g filter="url(#shadow)">
    <rect x="182" y="276" width="36" height="26" rx="10" fill="url(#metal)"/>
    <path d="M138 320 Q138 294 200 294 Q262 294 262 320 L254 392 Q248 430 200 432 Q152 430 146 392 Z" fill="url(#shell)" stroke="#AFC0CD" stroke-width="2.5"/>
    <path d="M150 394 Q200 412 250 394" fill="none" stroke="#B5C5D1" stroke-width="3" stroke-linecap="round"/>
    {chest(expression)}
  </g>
  <!-- floating hands -->
  <g filter="url(#shadow)">
    <ellipse cx="112" cy="356" rx="20" ry="27" fill="url(#shell)" stroke="#AFC0CD" stroke-width="2.5" transform="rotate(16 112 356)"/>
    <path d="M100 338 Q112 330 126 336" fill="none" stroke="url(#teal)" stroke-width="6" stroke-linecap="round" transform="rotate(16 112 356)"/>
    <ellipse cx="288" cy="356" rx="20" ry="27" fill="url(#shell)" stroke="#AFC0CD" stroke-width="2.5" transform="rotate(-16 288 356)"/>
    <path d="M274 336 Q288 330 300 338" fill="none" stroke="url(#teal)" stroke-width="6" stroke-linecap="round" transform="rotate(-16 288 356)"/>
  </g>"""


HEAD = """
  <!-- antenna with the golden bell (叮) -->
  <line x1="200" y1="66" x2="200" y2="42" stroke="url(#metal)" stroke-width="6" stroke-linecap="round"/>
  <circle cx="200" cy="66" r="8" fill="url(#teal)"/>
  <g filter="url(#shadow)">
    <path d="M184 40 Q184 14 200 14 Q216 14 216 40 L222 46 Q200 51 178 46 Z" fill="url(#gold)" stroke="#9C6A10" stroke-width="2"/>
    <ellipse cx="193" cy="26" rx="4" ry="7" fill="#FFFFFF" opacity="0.6"/>
    <circle cx="200" cy="50" r="4.5" fill="#9C6A10"/>
  </g>
  <!-- ear pods -->
  <g filter="url(#shadow)">
    <circle cx="56" cy="182" r="27" fill="url(#teal)"/>
    <circle cx="56" cy="182" r="15" fill="url(#shell)"/>
    <circle cx="344" cy="182" r="27" fill="url(#teal)"/>
    <circle cx="344" cy="182" r="15" fill="url(#shell)"/>
  </g>
  <!-- head shell -->
  <g filter="url(#shadow)">
    <rect x="60" y="64" width="280" height="226" rx="108" fill="url(#shell)" stroke="#AFC0CD" stroke-width="2.5"/>
  </g>
  <path d="M96 112 Q130 76 200 72" fill="none" stroke="#FFFFFF" stroke-width="10" stroke-linecap="round" opacity="0.85"/>
  <!-- glass visor -->
  <rect x="92" y="102" width="216" height="156" rx="72" fill="url(#visor)" stroke="#0A121C" stroke-width="4"/>
  <path d="M120 128 Q150 110 196 110" fill="none" stroke="#FFFFFF" stroke-width="7" stroke-linecap="round" opacity="0.16"/>
  <circle cx="284" cy="132" r="5" fill="#FFFFFF" opacity="0.18"/>"""


def _stroke(d: str, color: str, width: float = 8) -> str:
    return (
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
        'stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)"/>'
    )


def _shape(d: str, color: str) -> str:
    return f'<path d="{d}" fill="{color}" filter="url(#glow)"/>'


def _ellipse(cx: float, cy: float, rx: float, ry: float, color: str) -> str:
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{color}" filter="url(#glow)"/>'


def eyes(expression: str, blink: bool = False) -> str:
    c = glow_color(expression)
    if blink:
        return _stroke("M146 180 Q160 186 174 180", c, 7) + _stroke("M226 180 Q240 186 254 180", c, 7)
    if expression in ("smile", "happy"):
        w = 8 if expression == "happy" else 7
        return _stroke("M144 184 Q160 164 176 184", c, w) + _stroke("M224 184 Q240 164 256 184", c, w)
    if expression == "sad":
        return (
            _ellipse(160, 184, 12, 15, c) + _ellipse(240, 184, 12, 15, c)
            + _stroke("M142 160 L174 150", c, 5) + _stroke("M226 150 L258 160", c, 5)
        )
    if expression == "angry":
        return (
            _shape("M146 172 L176 182 Q174 196 161 196 Q146 196 146 182 Z", c)
            + _shape("M254 172 L224 182 Q226 196 239 196 Q254 196 254 182 Z", c)
            + _stroke("M140 154 L178 168", c, 6) + _stroke("M260 154 L222 168", c, 6)
        )
    if expression == "surprised":
        return (
            f'<circle cx="160" cy="178" r="19" fill="none" stroke="{c}" stroke-width="6" filter="url(#glow)"/>'
            f'<circle cx="240" cy="178" r="19" fill="none" stroke="{c}" stroke-width="6" filter="url(#glow)"/>'
            + _ellipse(160, 178, 6, 6, c) + _ellipse(240, 178, 6, 6, c)
            + _stroke("M144 146 Q160 138 176 146", c, 5) + _stroke("M224 146 Q240 138 256 146", c, 5)
        )
    if expression == "worried":
        return (
            _ellipse(160, 184, 12, 16, c) + _ellipse(240, 184, 12, 16, c)
            + _stroke("M144 158 Q160 150 176 156", c, 5) + _stroke("M224 156 Q240 150 256 158", c, 5)
        )
    if expression == "thinking":
        return (
            _ellipse(168, 176, 12, 16, c) + _ellipse(248, 176, 12, 16, c)
            + _stroke("M152 152 L182 152", c, 5) + _stroke("M232 146 Q248 136 264 146", c, 5)
        )
    return _ellipse(160, 180, 14, 19, c) + _ellipse(240, 180, 14, 19, c)


def mouth(expression: str, level: int) -> str:
    c = glow_color(expression)
    if level == 0:
        rest = {
            "neutral": _stroke("M186 226 Q200 234 214 226", c, 6),
            "smile": _stroke("M178 222 Q200 242 222 222", c, 7),
            "happy": _shape("M176 218 L224 218 Q224 250 200 252 Q176 250 176 218 Z", c),
            "sad": _stroke("M184 236 Q200 224 216 236", c, 6),
            "angry": _stroke("M182 232 L191 226 L200 232 L209 226 L218 232", c, 5),
            "surprised": f'<circle cx="200" cy="232" r="9" fill="none" stroke="{c}" stroke-width="5" filter="url(#glow)"/>',
            "worried": _stroke("M180 232 Q185 226 190 232 T200 232 T210 232 T220 232", c, 5),
            "thinking": _stroke("M190 230 L212 226", c, 6),
        }
        return rest[expression]
    h = {1: 7, 2: 11, 3: 15}[level]
    if expression in ("smile", "happy"):
        w = {1: 16, 2: 19, 3: 22}[level] + (3 if expression == "happy" else 0)
        return _shape(
            f"M{200 - w} 220 L{200 + w} 220 Q{200 + w} {222 + 2 * h} 200 {224 + 2 * h} "
            f"Q{200 - w} {222 + 2 * h} {200 - w} 220 Z",
            c,
        )
    if expression == "surprised":
        r = {1: 10, 2: 12, 3: 15}[level]
        return f'<circle cx="200" cy="234" r="{r}" fill="none" stroke="{c}" stroke-width="5" filter="url(#glow)"/>'
    if expression == "angry":
        w = {1: 13, 2: 16, 3: 19}[level]
        return f'<rect x="{200 - w}" y="{230 - h // 2}" width="{2 * w}" height="{h + 3}" rx="5" fill="{c}" filter="url(#glow)"/>'
    w = {1: 9, 2: 11, 3: 13}[level]
    y = 234 if expression in ("sad", "worried") else 230
    return _ellipse(200, y, w, h // 2 + 3, c)


def extras(expression: str) -> str:
    parts: list[str] = []
    if expression in ("smile", "happy"):
        opacity = "0.55" if expression == "happy" else "0.4"
        parts.append(
            f'<ellipse cx="130" cy="214" rx="15" ry="8" fill="{PINK}" opacity="{opacity}" filter="url(#soft)"/>'
            f'<ellipse cx="270" cy="214" rx="15" ry="8" fill="{PINK}" opacity="{opacity}" filter="url(#soft)"/>'
        )
    if expression == "happy":
        star = "M0 -12 Q2.5 -2.5 12 0 Q2.5 2.5 0 12 Q-2.5 2.5 -12 0 Q-2.5 -2.5 0 -12 Z"
        for x, y, s in ((40, 96, 1.0), (360, 112, 0.8), (346, 64, 0.55)):
            parts.append(f'<path d="{star}" fill="{GOLD}" transform="translate({x} {y}) scale({s})"/>')
    if expression == "sad":
        parts.append(f'<path d="M152 204 Q147 216 152 221 Q158 224 161 217 Q161 211 152 204 Z" fill="{BLUE}" filter="url(#glow)"/>')
    if expression == "angry":
        parts.append('<rect x="92" y="102" width="216" height="156" rx="72" fill="#FF3B3B" opacity="0.10"/>')
        mark = "M-10 -4 Q0 -2 4 -10 M10 4 Q0 2 -4 10 M-4 -10 Q-2 0 -10 4 M4 10 Q2 0 10 -4"
        parts.append(f'<path d="{mark}" fill="none" stroke="#FF5A5F" stroke-width="4.5" stroke-linecap="round" transform="translate(318 92) scale(1.5)"/>')
    if expression == "worried":
        parts.append('<path d="M330 112 Q320 130 328 138 Q338 142 342 132 Q342 122 330 112 Z" fill="url(#drop)" stroke="#5FAAD8" stroke-width="1.5"/>')
    if expression == "thinking":
        for x, y, r in ((328, 76, 5), (346, 56, 7), (368, 32, 10)):
            parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="url(#shell)" stroke="#AFC0CD" stroke-width="2"/>')
    return "".join(parts)


def svg(expression: str, level: int = 0, blink: bool = False) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 470" width="400" height="470">'
        f"<title>叮當 · {expression}</title>{DEFS}"
        f"{body(expression)}{HEAD}{eyes(expression, blink)}{mouth(expression, level)}{extras(expression)}"
        "</svg>\n"
    )


def main() -> None:
    for expression in EXPRESSIONS:
        folder = OUT / expression
        folder.mkdir(parents=True, exist_ok=True)
        for level in range(4):
            (folder / f"{level:03d}.svg").write_text(svg(expression, level), encoding="utf-8")
    (OUT / "blink.svg").write_text(svg("neutral", 0, blink=True), encoding="utf-8")
    (OUT / "smile_blink.svg").write_text(svg("smile", 0, blink=True), encoding="utf-8")
    print(f"wrote {len(EXPRESSIONS) * 4 + 2} SVG frames to {OUT}")


if __name__ == "__main__":
    main()
