"""
Local icon system - no external icon CDN of any kind.

Usage in templates:  {% icon "airplane" %}  or  {% icon "airplane" size=20 class_="me-2" %}

Icons are stored as small SVG files in static/icons/<name>.svg. This tag reads
the file content and inlines it directly into the page (cached in memory after
first read), so icons pick up `currentColor` for theming through CSS and never
trigger a network request.
"""
import os
from functools import lru_cache
from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()

ICONS_DIR = settings.BASE_DIR / "static" / "icons"


@lru_cache(maxsize=128)
def _read_icon(name):
    path = ICONS_DIR / f"{name}.svg"
    if not path.exists():
        return None
    return path.read_text()


@register.simple_tag
def icon(name, size=18, class_=""):
    raw = _read_icon(name)
    if raw is None:
        return mark_safe(f"<!-- icon '{name}' not found -->")
    # Inject sizing + class onto the root <svg ...> tag without needing an XML parser.
    svg = raw.replace("<svg ", f'<svg width="{size}" height="{size}" class="af-icon {class_}" ', 1)
    return mark_safe(svg)
