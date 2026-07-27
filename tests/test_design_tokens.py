"""Guards the interface's token layer: the native font stack and the teal accent.

DESIGN.md names the token layer as the system's main drift risk — a hue or hex
edited in one component rule without updating the `:root` declaration it should
have come from. These tests parse the live `app/static/style.css` and
`app/templates/base.html` from disk (never a copy, never a snapshot) so a future
token edit cannot silently drift past this gate.

The WCAG contrast function below is intentionally reimplemented locally rather
than pulled from a library: the guard should add zero dependency surface to the
suite, and the relative-luminance formula is short and stable enough that a
local copy is the simpler, more auditable choice.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STYLE_PATH = _REPO_ROOT / "app" / "static" / "style.css"
_BASE_HTML_PATH = _REPO_ROOT / "app" / "templates" / "base.html"
_APP_DIR = _REPO_ROOT / "app"

_STYLE_CSS = _STYLE_PATH.read_text()
_BASE_HTML = _BASE_HTML_PATH.read_text()

# The new, post-swap values (D-02). Kept as module constants so every test that
# needs "the new accent" reads the same source of truth instead of retyping hex.
_NEW_ACCENT = "#0F5F5C"
_NEW_ACCENT_HOVER = "#0B4A48"
_NEW_ACCENT_RING = "rgba(15, 95, 92, 0.18)"

# The superseded, pre-swap values. Asserted absent, never present.
_OLD_ACCENT = "#4F46E5"
_OLD_ACCENT_HOVER = "#4338CA"
_OLD_ACCENT_RING = "rgba(79, 70, 229, 0.18)"
_OLD_CLARIFICATION_BG = "#EEF2FF"

_STATE_PENDING_TOKENS = {
    "--state-pending-fg": "#3730A3",
    "--state-pending-bg": "#EEF0FE",
    "--state-pending-edge": "#C7D2FE",
    "--state-pending-edge-strong": "#A5B4FC",
}


def _extract_root_block(css: str) -> str:
    """Return the contents of the first `:root { ... }` block in the stylesheet."""
    match = re.search(r":root\s*\{(.*?)\n\}", css, re.DOTALL)
    assert match is not None, "style.css has no :root block to parse"
    return match.group(1)


def _parse_custom_properties(root_block: str) -> dict[str, str]:
    """Parse `--name: value;` declarations out of a `:root` block body."""
    tokens: dict[str, str] = {}
    for line in root_block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("--") or ":" not in stripped:
            continue
        name, _, value = stripped.partition(":")
        tokens[name.strip()] = value.strip().rstrip(";").strip()
    return tokens


_ROOT_BLOCK = _extract_root_block(_STYLE_CSS)
_ROOT_TOKENS = _parse_custom_properties(_ROOT_BLOCK)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Parse a `#RRGGBB` hex color string into an (r, g, b) integer tuple."""
    stripped = value.strip().lstrip("#")
    assert len(stripped) == 6, f"expected a 6-digit hex color, got {value!r}"
    return (
        int(stripped[0:2], 16),
        int(stripped[2:4], 16),
        int(stripped[4:6], 16),
    )


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x relative luminance for an sRGB (r, g, b) triple, each in 0-255."""

    def _channel(component: int) -> float:
        c = component / 255.0
        if c <= 0.03928:
            return c / 12.92
        return float(((c + 0.055) / 1.055) ** 2.4)

    r, g, b = rgb
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG 2.x contrast ratio between two `#RRGGBB` colors, always >= 1.0."""
    lum_a = _relative_luminance(_hex_to_rgb(hex_a))
    lum_b = _relative_luminance(_hex_to_rgb(hex_b))
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def test_no_third_party_font_request() -> None:
    """base.html requests no third-party origin for type; the only stylesheet is local."""
    lowered = _BASE_HTML.lower()
    assert "fonts.googleapis.com" not in lowered
    assert "fonts.gstatic.com" not in lowered
    assert "rel=\"preconnect\"" not in lowered
    assert "rel='preconnect'" not in lowered

    stylesheet_hrefs = re.findall(
        r'<link[^>]+rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)["\']', _BASE_HTML
    )
    assert stylesheet_hrefs == ["/static/style.css"], (
        f"expected the only stylesheet link to be the local one, got {stylesheet_hrefs}"
    )
    assert not any(href.startswith(("http://", "https://")) for href in stylesheet_hrefs)


def test_font_sans_is_a_native_stack() -> None:
    """`--font-sans` begins with `system-ui` and names no downloadable family."""
    font_sans = _ROOT_TOKENS["--font-sans"]
    assert font_sans.startswith("system-ui"), font_sans
    assert "Inter" not in font_sans


def test_accent_and_pending_tokens_declared_at_new_values() -> None:
    """`:root` declares the new accent trio and all four waiting-family tokens."""
    assert _ROOT_TOKENS["--accent"] == _NEW_ACCENT
    assert _ROOT_TOKENS["--accent-hover"] == _NEW_ACCENT_HOVER
    assert _ROOT_TOKENS["--accent-ring"] == _NEW_ACCENT_RING
    for name, value in _STATE_PENDING_TOKENS.items():
        assert name in _ROOT_TOKENS, f"{name} missing from :root"
        assert _ROOT_TOKENS[name] == value, f"{name} = {_ROOT_TOKENS[name]!r}, expected {value!r}"


def test_accent_soft_deleted() -> None:
    """`--accent-soft` appears nowhere under app/ — it was deleted, not retinted."""
    for path in _APP_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".css", ".html", ".py"}:
            continue
        contents = path.read_text(errors="ignore")
        assert "accent-soft" not in contents, f"--accent-soft still referenced in {path}"


def test_superseded_accent_values_absent() -> None:
    """Neither the superseded accent hexes nor the superseded ring rgba survive."""
    for path in [_STYLE_PATH, *_REPO_ROOT.glob("app/templates/*.html")]:
        lowered = path.read_text().lower()
        assert _OLD_ACCENT.lower() not in lowered, f"{_OLD_ACCENT} still present in {path}"
        assert _OLD_ACCENT_HOVER.lower() not in lowered, (
            f"{_OLD_ACCENT_HOVER} still present in {path}"
        )
        assert _OLD_ACCENT_RING.lower() not in lowered, (
            f"{_OLD_ACCENT_RING} still present in {path}"
        )


def test_pending_family_tokens_are_the_single_source() -> None:
    """Each waiting-family hex appears exactly once in style.css: its :root declaration.

    This is the Token-First Rule made enforceable — a component rule may reference
    the token, but the literal hex it carries must live in exactly one place.
    """
    lowered = _STYLE_CSS.lower()
    for value in _STATE_PENDING_TOKENS.values():
        count = lowered.count(value.lower())
        assert count == 1, f"{value} appears {count} times in style.css, expected exactly 1"
    assert _OLD_CLARIFICATION_BG.lower() not in lowered, (
        f"superseded clarification-card background {_OLD_CLARIFICATION_BG} still present"
    )


def test_accent_and_pending_contrast_clears_aa() -> None:
    """Every accent-bearing and pending-status pair clears WCAG AA 4.5:1.

    Ratios are computed from the hexes parsed out of the live :root block, so
    this gate can never drift from the stylesheet it is guarding.
    """
    surface = _ROOT_TOKENS["--surface"]
    bg = _ROOT_TOKENS["--bg"]
    surface_subtle = _ROOT_TOKENS["--surface-subtle"]
    accent = _ROOT_TOKENS["--accent"]
    accent_hover = _ROOT_TOKENS["--accent-hover"]
    pending_fg = _ROOT_TOKENS["--state-pending-fg"]
    pending_bg = _ROOT_TOKENS["--state-pending-bg"]

    pairs = {
        "white-on-accent (primary button)": ("#FFFFFF", accent),
        "white-on-accent-hover": ("#FFFFFF", accent_hover),
        "accent-on-surface (in-table links)": (accent, surface),
        "accent-on-page-ground (footer links)": (accent, bg),
        "accent-on-surface-subtle": (accent, surface_subtle),
        "pending-fg-on-pending-bg": (pending_fg, pending_bg),
    }

    for label, (fg, bg_color) in pairs.items():
        ratio = _contrast_ratio(fg, bg_color)
        assert ratio >= 4.5, (
            f"{label}: {fg} on {bg_color} measures {ratio:.2f}:1, below WCAG AA 4.5:1"
        )
