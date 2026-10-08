"""Explicit graphics dispatch; profile generation lists have no role here."""

from collections.abc import Sequence

from clipfactory.domain.graphics import VisualKind
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import VideoProvider


def graphics_provider(kind: VisualKind, providers: Sequence[VideoProvider]) -> VideoProvider:
    name = {"infographic": "hyperframes", "scientific": "manim"}.get(kind)
    if name is None:
        raise ProviderError("unsupported_graphics_template", "Media is not a graphics route", transient=False)
    for provider in providers:
        if provider.name == name:
            return provider
    raise ProviderError("graphics_render_failed", f"Configure the local {name} renderer", transient=False)
