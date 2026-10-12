"""Trusted infographic HTML. Data is escaped, never interpreted as source."""

import re
from html import escape

from clipfactory.domain.graphics import Comparison, KeyDate, Statistic, Timeline, graphics_number
from clipfactory.ports.generation import VideoGenerationRequest

_MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_ORDINAL_DAYS = {
    word: str(day)
    for day, word in enumerate(
        [
            "first",
            "second",
            "third",
            "fourth",
            "fifth",
            "sixth",
            "seventh",
            "eighth",
            "ninth",
            "tenth",
            "eleventh",
            "twelfth",
            "thirteenth",
            "fourteenth",
            "fifteenth",
            "sixteenth",
            "seventeenth",
            "eighteenth",
            "nineteenth",
            "twentieth",
        ],
        start=1,
    )
}


def _calendar_parts(text: str) -> tuple[str, str, str] | None:
    """Split a grounded date into (month, day, year) for the calendar layout, if it has that shape."""
    words = re.findall(r"[^\W_]+", text.casefold())
    month = next(
        (name for name in _MONTHS if any(word == name or (len(word) >= 3 and name.startswith(word)) for word in words)),
        None,
    )
    day = next(
        (
            _ORDINAL_DAYS.get(word) or re.sub(r"(st|nd|rd|th)$", "", word)
            for word in words
            if word in _ORDINAL_DAYS or re.fullmatch(r"(?:[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?", word)
        ),
        None,
    )
    year = next((word for word in words if re.fullmatch(r"(?:19|20)\d\d", word)), "")
    if month is None or day is None:
        return None
    return month.capitalize(), day, year


def _key_date_html(request: VideoGenerationRequest, spec: KeyDate) -> str:
    parts = _calendar_parts(spec.date.text)
    if parts is None:
        page = f'<div class="day text">{escape(spec.date.text)}</div>'
    else:
        month, day, year = parts
        page = (
            f'<div class="month">{escape(month)}</div><div class="day">{escape(day)}</div>'
            f'<div class="year">{escape(year)}</div>'
        )
    caption = f'<p class="caption">{escape(spec.title.text)}</p>' if spec.title is not None else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<script src="./gsap.min.js"></script><style>
body{{margin:0;background:#0b1a33;color:#fff;font-family:DejaVu Sans,sans-serif}}
#root{{width:{request.width}px;height:{request.height}px;overflow:hidden;position:relative;
background:radial-gradient(circle at 50% 38%,#1d3d6e 0%,#0b1a33 70%)}}
section{{box-sizing:border-box;width:100%;height:100%;padding:8%;display:flex;flex-direction:column;
align-items:center;justify-content:center;gap:40px}}
.label{{font-size:30px;letter-spacing:8px;color:#9cc4ff;font-weight:700}}
.card{{width:62%;background:#fff;border-radius:28px;overflow:hidden;text-align:center;color:#0b1a33;
box-shadow:0 24px 60px rgba(0,0,0,.45)}}
.month{{background:#1554c0;color:#fff;font-size:52px;font-weight:700;padding:22px 0;letter-spacing:2px}}
.day{{font-size:220px;font-weight:700;line-height:1;padding:36px 0 12px}}
.day.text{{font-size:64px;padding:64px 24px}}
.year{{font-size:40px;color:#41557a;padding-bottom:30px;min-height:10px}}
.caption{{font-size:36px;margin:0;text-align:center;max-width:90%;line-height:1.3}}
</style></head><body>
<div id="root" data-composition-id="graphic" data-width="{request.width}" data-height="{request.height}"
data-duration="{request.duration_seconds}" data-start="0">
<section class="clip" data-start="0" data-duration="{request.duration_seconds}">
<div class="label">KEY DATE</div><div class="card">{page}</div>{caption}
</section></div>
<script>
const tl = gsap.timeline({{paused:true}});
tl.from(".card", {{opacity:0,scale:0.8,y:40,duration:{min(request.duration_seconds * 0.3, 0.9)},
ease:"back.out(1.6)"}},0);
tl.from([".label",".caption"], {{opacity:0,y:16,duration:0.6,stagger:0.2,ease:"power2.out"}},0.3);
window.__timelines["graphic"]=tl;
</script></body></html>"""


def infographic_html(request: VideoGenerationRequest) -> str:
    spec = request.graphics_spec
    if isinstance(spec, KeyDate):
        return _key_date_html(request, spec)
    if not isinstance(spec, Statistic | Comparison | Timeline):
        raise ValueError("unsupported_graphics_template")
    cards: list[str] = []
    if isinstance(spec, Statistic):
        cards = [f"<strong>{graphics_number(spec.item.value)}</strong><p>{escape(spec.item.label.text)}</p>"]
    elif isinstance(spec, Comparison):
        maximum = max(abs(item.value) for item in spec.items) or 1
        cards = [
            f"<p>{escape(item.label.text)}: {graphics_number(item.value)}</p>"
            f'<div class="bar" style="transform:scaleX({abs(item.value) / maximum})"></div>'
            for item in spec.items
        ]
    else:
        cards = [
            f"<strong>{escape(event.date.text)}</strong><p>{escape(event.label.text)}</p>" for event in spec.events
        ]
    content = "".join(f'<article class="item">{card}</article>' for card in cards)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<script src="./gsap.min.js"></script><style>
body{{margin:0;background:#101c30;color:#fff;font-family:DejaVu Sans,sans-serif}}
#root{{width:{request.width}px;height:{request.height}px;overflow:hidden;position:relative}}
section{{box-sizing:border-box;width:100%;height:100%;padding:8%;display:flex;flex-direction:column;
justify-content:center;gap:24px}}h1{{font-size:42px;margin:0}}p{{font-size:28px;margin:12px 0}}
strong{{font-size:38px}}.item{{padding:16px;background:#243852;border-radius:12px}}
.bar{{height:12px;width:100%;background:#64d8ef;transform-origin:left}}
</style></head><body>
<div id="root" data-composition-id="graphic" data-width="{request.width}" data-height="{request.height}"
data-duration="{request.duration_seconds}" data-start="0">
<section class="clip" data-start="0" data-duration="{request.duration_seconds}">
<h1>{escape(spec.title.text)}</h1>{content}
{"<p>Bar length shows absolute magnitude; values retain their signs.</p>" if isinstance(spec, Comparison) else ""}
</section></div>
<script>
const tl = gsap.timeline({{paused:true}});
tl.from(".item", {{opacity:0,y:16,duration:{min(request.duration_seconds * 0.4, 1.5)},
stagger:{request.duration_seconds * 0.4 / len(cards)},ease:"power2.out"}},0);
window.__timelines["graphic"]=tl;
</script></body></html>"""
