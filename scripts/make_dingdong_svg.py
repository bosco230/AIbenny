"""Generate the original 叮當 character: a chibi (Q版) boy.

Writes characters/dingdong/faces/<expression>/000.svg (resting mouth) and
001-003.svg (speaking mouth, small -> wide), plus faces/blink.svg and
faces/smile_blink.svg.

Expressions: neutral, smile, happy, sad, angry, surprised, worried, thinking.

Design: big head, short body; dark-brown spiky fringe; large eyes with two
highlights; blue zip-less hoodie with kangaroo pocket and drawstrings, a
little gold bell on the right drawstring (the "叮"); jeans and white
sneakers. Deliberately original.

Usage:  python -I scripts/make_dingdong_svg.py
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "characters" / "dingdong" / "faces"

EXPRESSIONS = ("neutral", "smile", "happy", "sad", "angry", "surprised", "worried", "thinking")

LINE = "#3A2A22"       # facial line colour
IRIS = "#4A2F22"
MOUTH = "#8B2E3B"
TONGUE = "#F2897F"
BLUSH = "#FF9A9A"
TEAR = "#8FD0FF"
GOLD = "#FFD36A"

DEFS = """
<defs>
  <radialGradient id="skin" cx="0.45" cy="0.38" r="0.75">
    <stop offset="0" stop-color="#FFEBDA"/>
    <stop offset="1" stop-color="#F4C7A4"/>
  </radialGradient>
  <linearGradient id="hair" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#5A3E30"/>
    <stop offset="1" stop-color="#2E1F18"/>
  </linearGradient>
  <linearGradient id="hoodie" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#6A93D0"/>
    <stop offset="1" stop-color="#3F64A0"/>
  </linearGradient>
  <linearGradient id="hoodieDark" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#557FBE"/>
    <stop offset="1" stop-color="#365791"/>
  </linearGradient>
  <linearGradient id="jeans" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#3B4C70"/>
    <stop offset="1" stop-color="#2A3754"/>
  </linearGradient>
  <radialGradient id="iris" cx="0.5" cy="0.35" r="0.7">
    <stop offset="0" stop-color="#7A5038"/>
    <stop offset="1" stop-color="#2B1B14"/>
  </radialGradient>
  <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#FFF1B0"/>
    <stop offset="0.5" stop-color="#F2BE45"/>
    <stop offset="1" stop-color="#B57A12"/>
  </linearGradient>
  <radialGradient id="ground" cx="0.5" cy="0.5" r="0.5">
    <stop offset="0" stop-color="#000" stop-opacity="0.25"/>
    <stop offset="1" stop-color="#000" stop-opacity="0"/>
  </radialGradient>
  <filter id="soft" x="-40%" y="-40%" width="180%" height="180%">
    <feGaussianBlur stdDeviation="4"/>
  </filter>
  <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">
    <feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#2A2030" flood-opacity="0.18"/>
  </filter>
</defs>"""

BODY = """
  <ellipse cx="200" cy="456" rx="92" ry="12" fill="url(#ground)"/>
  <g filter="url(#shadow)">
    <!-- legs + sneakers -->
    <rect x="160" y="410" width="36" height="34" rx="10" fill="url(#jeans)"/>
    <rect x="204" y="410" width="36" height="34" rx="10" fill="url(#jeans)"/>
    <ellipse cx="174" cy="446" rx="28" ry="12" fill="#FFFFFF" stroke="#B8C2CC" stroke-width="2.5"/>
    <ellipse cx="226" cy="446" rx="28" ry="12" fill="#FFFFFF" stroke="#B8C2CC" stroke-width="2.5"/>
    <path d="M150 446 L198 446 M202 446 L250 446" stroke="#D9E0E6" stroke-width="3"/>
    <!-- sleeves + hands -->
    <rect x="98" y="312" width="42" height="86" rx="21" fill="url(#hoodieDark)" transform="rotate(14 119 355)"/>
    <rect x="260" y="312" width="42" height="86" rx="21" fill="url(#hoodieDark)" transform="rotate(-14 281 355)"/>
    <circle cx="108" cy="398" r="16" fill="url(#skin)" stroke="#E3AE88" stroke-width="2"/>
    <circle cx="292" cy="398" r="16" fill="url(#skin)" stroke="#E3AE88" stroke-width="2"/>
    <!-- hoodie -->
    <path d="M124 316 Q126 290 200 290 Q274 290 276 316 L284 408 Q284 420 272 420 L128 420 Q116 420 116 408 Z" fill="url(#hoodie)"/>
    <path d="M150 380 Q200 370 250 380 L254 410 L146 410 Z" fill="url(#hoodieDark)"/>
    <path d="M150 380 Q200 370 250 380" fill="none" stroke="#2F4F86" stroke-width="2.5"/>
    <path d="M148 296 Q200 336 252 296" fill="none" stroke="#86A9DC" stroke-width="12" stroke-linecap="round"/>
    <!-- drawstrings, gold bell on the right one (the 叮) -->
    <path d="M184 316 Q182 336 180 352" fill="none" stroke="#F2F4F7" stroke-width="4" stroke-linecap="round"/>
    <path d="M216 316 Q218 334 220 346" fill="none" stroke="#F2F4F7" stroke-width="4" stroke-linecap="round"/>
    <path d="M211 354 Q211 343 220 343 Q229 343 229 354 L232 358 Q220 361 208 358 Z" fill="url(#gold)" stroke="#9C6A10" stroke-width="1.5"/>
    <circle cx="220" cy="361" r="2.5" fill="#9C6A10"/>
  </g>
  <rect x="186" y="282" width="28" height="18" rx="6" fill="#EDB993"/>"""

HEAD = """
  <!-- back hair, ears, face -->
  <ellipse cx="200" cy="168" rx="134" ry="114" fill="url(#hair)"/>
  <ellipse cx="78" cy="212" rx="17" ry="23" fill="url(#skin)" stroke="#E3AE88" stroke-width="2"/>
  <ellipse cx="322" cy="212" rx="17" ry="23" fill="url(#skin)" stroke="#E3AE88" stroke-width="2"/>
  <ellipse cx="200" cy="196" rx="124" ry="106" fill="url(#skin)"/>
  <!-- front fringe -->
  <path d="M80 196 Q66 92 160 62 Q240 40 302 78 Q342 104 328 194 L314 160 Q302 152 298 132
           L276 156 Q262 140 258 118 L236 150 Q220 126 214 106 L196 146 Q178 126 172 106
           L152 148 Q134 132 128 112 L108 158 Q96 152 92 138 Z" fill="url(#hair)"/>
  <path d="M132 84 Q170 66 214 68" fill="none" stroke="#8A6650" stroke-width="7" stroke-linecap="round" opacity="0.7"/>
  <path d="M188 70 Q196 58 206 50" fill="none" stroke="url(#hair)" stroke-width="10" stroke-linecap="round"/>
  <!-- nose -->
  <path d="M198 232 Q201 236 204 232" fill="none" stroke="#D89A78" stroke-width="3" stroke-linecap="round"/>"""


def _line(d: str, width: float = 5, color: str = LINE) -> str:
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>'


def _eye(cx: float, cy: float, rx: float = 17, ry: float = 22, look: tuple[float, float] = (0, 0)) -> str:
    lx, ly = look
    return (
        f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="url(#iris)"/>'
        f'<circle cx="{cx + rx * 0.3 + lx}" cy="{cy - ry * 0.38 + ly}" r="{rx * 0.36}" fill="#FFFFFF"/>'
        f'<circle cx="{cx - rx * 0.35 + lx}" cy="{cy + ry * 0.35 + ly}" r="{rx * 0.17}" fill="#FFFFFF" opacity="0.85"/>'
        + _line(f"M{cx - rx - 3} {cy - ry + 4} Q{cx} {cy - ry - 8} {cx + rx + 3} {cy - ry + 4}", 4)
    )


def brows(kind: str) -> str:
    shapes = {
        "relaxed": ("M138 170 Q158 162 178 168", "M222 168 Q242 162 262 170"),
        "up": ("M138 164 Q158 154 178 160", "M222 160 Q242 154 262 164"),
        "sad": ("M140 166 Q160 166 178 154", "M222 154 Q240 166 260 166"),
        "angry": ("M140 158 Q162 162 180 174", "M220 174 Q238 162 260 158"),
        "think": ("M140 168 Q160 164 178 168", "M222 156 Q242 146 262 156"),
    }
    left, right = shapes[kind]
    return _line(left, 6) + _line(right, 6)


def eyes(expression: str, blink: bool = False) -> str:
    if blink:
        closed = _line("M142 212 Q160 222 178 212", 5) + _line("M222 212 Q240 222 258 212", 5)
        return brows("relaxed") + closed
    if expression == "happy":
        return brows("up") + _line("M142 216 Q160 196 178 216", 6) + _line("M222 216 Q240 196 258 216", 6)
    if expression == "smile":
        lids = _line("M144 222 Q160 228 176 222", 3, "#C98E6E") + _line("M224 222 Q240 228 256 222", 3, "#C98E6E")
        return brows("relaxed") + _eye(160, 208, 16, 19) + _eye(240, 208, 16, 19) + lids
    if expression == "sad":
        return brows("sad") + _eye(160, 212, 15, 19) + _eye(240, 212, 15, 19)
    if expression == "angry":
        lids = (
            '<path d="M138 192 L182 204 L182 194 L138 186 Z" fill="url(#skin)"/>'
            '<path d="M262 192 L218 204 L218 194 L262 186 Z" fill="url(#skin)"/>'
        )
        return _eye(160, 212, 15, 17) + _eye(240, 212, 15, 17) + lids + brows("angry")
    if expression == "surprised":
        def ring(cx: float) -> str:
            return (
                f'<ellipse cx="{cx}" cy="208" rx="19" ry="24" fill="#FFFFFF" stroke="{LINE}" stroke-width="4"/>'
                f'<circle cx="{cx}" cy="208" r="9" fill="url(#iris)"/><circle cx="{cx + 3}" cy="204" r="3" fill="#FFFFFF"/>'
            )
        return brows("up") + ring(160) + ring(240)
    if expression == "worried":
        return brows("sad") + _eye(160, 210, 15, 20) + _eye(240, 210, 15, 20)
    if expression == "thinking":
        return brows("think") + _eye(160, 208, 16, 21, (5, -5)) + _eye(240, 208, 16, 21, (5, -5))
    return brows("relaxed") + _eye(160, 210) + _eye(240, 210)


def _open(w: float, h: float, y: float = 256, teeth: bool = False) -> str:
    d = f"M{200 - w} {y} Q200 {y - 4} {200 + w} {y} Q{200 + w * 0.8} {y + h} 200 {y + h + 2} Q{200 - w * 0.8} {y + h} {200 - w} {y} Z"
    parts = [f'<path d="{d}" fill="{MOUTH}" stroke="{LINE}" stroke-width="3" stroke-linejoin="round"/>']
    if h >= 10:
        parts.append(f'<ellipse cx="200" cy="{y + h - 3}" rx="{w * 0.5}" ry="{h * 0.3}" fill="{TONGUE}"/>')
    if teeth:
        parts.append(f'<path d="M{200 - w + 5} {y + 1} L{200 + w - 5} {y + 1} L{200 + w - 8} {y + 6} L{200 - w + 8} {y + 6} Z" fill="#FFFFFF"/>')
    return "".join(parts)


def mouth(expression: str, level: int) -> str:
    if level == 0:
        rest = {
            "neutral": _line("M188 254 Q200 260 212 254", 4.5),
            "smile": _line("M180 250 Q200 266 220 250", 5),
            "happy": _open(24, 22, 250, teeth=True),
            "sad": _line("M186 262 Q200 252 214 262", 4.5),
            "angry": _line("M184 260 Q192 254 200 258 Q208 254 216 260", 4.5),
            "surprised": f'<ellipse cx="200" cy="260" rx="9" ry="11" fill="{MOUTH}" stroke="{LINE}" stroke-width="3"/>',
            "worried": _line("M184 260 Q190 254 196 260 T208 260 T216 258", 4),
            "thinking": _line("M192 258 L212 254", 4.5),
        }
        return rest[expression]
    if expression == "surprised":
        r = {1: 10, 2: 12, 3: 15}[level]
        return f'<ellipse cx="200" cy="262" rx="{r - 2}" ry="{r}" fill="{MOUTH}" stroke="{LINE}" stroke-width="3"/>'
    width = {1: 12, 2: 16, 3: 20}[level]
    height = {1: 7, 2: 12, 3: 18}[level]
    if expression in ("smile", "happy"):
        return _open(width + 6, height + 4, 250, teeth=level >= 2)
    if expression == "angry":
        return _open(width + 2, height, 254, teeth=True)
    y = 258 if expression in ("sad", "worried") else 254
    return _open(width, height, y)


def extras(expression: str) -> str:
    parts: list[str] = []
    if expression in ("neutral", "smile", "happy", "thinking", "surprised"):
        opacity = {"happy": "0.6", "smile": "0.5"}.get(expression, "0.3")
        parts.append(
            f'<ellipse cx="134" cy="244" rx="17" ry="9" fill="{BLUSH}" opacity="{opacity}" filter="url(#soft)"/>'
            f'<ellipse cx="266" cy="244" rx="17" ry="9" fill="{BLUSH}" opacity="{opacity}" filter="url(#soft)"/>'
        )
    if expression == "happy":
        star = "M0 -12 Q2.5 -2.5 12 0 Q2.5 2.5 0 12 Q-2.5 2.5 -12 0 Q-2.5 -2.5 0 -12 Z"
        for x, y, s in ((54, 110, 1.0), (350, 96, 0.85), (334, 54, 0.55)):
            parts.append(f'<path d="{star}" fill="{GOLD}" transform="translate({x} {y}) scale({s})"/>')
    if expression == "sad":
        parts.append(f'<path d="M152 232 Q146 246 152 252 Q160 256 163 248 Q163 240 152 232 Z" fill="{TEAR}" stroke="#5FAAD8" stroke-width="1.5"/>')
    if expression == "angry":
        mark = "M-10 -4 Q0 -2 4 -10 M10 4 Q0 2 -4 10 M-4 -10 Q-2 0 -10 4 M4 10 Q2 0 10 -4"
        parts.append(f'<path d="{mark}" fill="none" stroke="#E8434B" stroke-width="4.5" stroke-linecap="round" transform="translate(300 92) scale(1.5)"/>')
    if expression == "worried":
        parts.append('<path d="M300 150 Q290 168 298 176 Q308 180 312 170 Q312 160 300 150 Z" fill="#CDEBFF" stroke="#5FAAD8" stroke-width="1.5"/>')
    if expression == "thinking":
        for x, y, r in ((330, 92, 5), (348, 70, 7), (370, 44, 10)):
            parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#FFFFFF" stroke="#C7D0D8" stroke-width="2"/>')
    return "".join(parts)


def svg(expression: str, level: int = 0, blink: bool = False) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 470" width="400" height="470">'
        f"<title>叮當 · {expression}</title>{DEFS}{BODY}{HEAD}"
        f"{extras(expression)}{eyes(expression, blink)}{mouth(expression, level)}"
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
