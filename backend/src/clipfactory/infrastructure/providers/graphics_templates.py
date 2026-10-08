"""Trusted infographic HTML. Data is escaped, never interpreted as source."""

from html import escape

from clipfactory.domain.graphics import Comparison, Statistic, Timeline, graphics_number
from clipfactory.ports.generation import VideoGenerationRequest


def infographic_html(request: VideoGenerationRequest) -> str:
    spec = request.graphics_spec
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
