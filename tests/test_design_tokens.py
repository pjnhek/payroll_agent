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

import os
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STYLE_PATH = _REPO_ROOT / "app" / "static" / "style.css"
_BASE_HTML_PATH = _REPO_ROOT / "app" / "templates" / "base.html"
_APP_DIR = _REPO_ROOT / "app"
_FRONTEND_SRC_DIR = _REPO_ROOT / "frontend" / "src"

# The token/a11y scan's suffix allowlist, widened from {".css", ".html",
# ".py"} to also see .ts/.tsx — otherwise the guard goes blind the moment a
# page's markup moves into a React component.
_SCANNED_SUFFIXES = frozenset({".css", ".html", ".py", ".ts", ".tsx"})

_STYLE_CSS = _STYLE_PATH.read_text()
_BASE_HTML = _BASE_HTML_PATH.read_text()

# The new, post-swap accent values. Kept as module constants so every test that
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


def _extract_media_block(css: str, media_query: str) -> str:
    """Return the contents of the first `@media (<media_query>) { ... }` block.

    Brace-balanced rather than a lazy-`.*?` regex, since the block contains
    nested rule bodies with their own `{`/`}` pairs.
    """
    pattern = re.escape(f"@media ({media_query})") + r"\s*\{"
    match = re.search(pattern, css)
    assert match is not None, f"no @media ({media_query}) block found in style.css"
    body = css[match.end() :]
    depth = 1
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return body[:i]
    raise AssertionError(f"@media ({media_query}) block in style.css never closes")


def _extract_rule_body(css: str, selector: str) -> str:
    """Return the body of the first exact-selector CSS rule (e.g. `.btn-accent`)."""
    pattern = re.escape(selector) + r"\s*\{([^}]*)\}"
    match = re.search(pattern, css)
    assert match is not None, f"no {selector} {{ ... }} rule found in style.css"
    return match.group(1)


def _declared_properties(rule_body: str) -> set[str]:
    """Property names declared directly in a CSS rule body (not comments)."""
    props: set[str] = set()
    for line in rule_body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        if ":" in stripped:
            props.add(stripped.split(":", 1)[0].strip())
    return props


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


def _frontend_src_files() -> list[Path]:
    """Every `.ts`/`.tsx` file under `frontend/src`, or an empty list when the
    directory does not yet exist.

    This plan (22-02) runs BEFORE the Vite scaffold (a later plan in this
    phase) creates `frontend/`, so an absent directory must be a structural
    no-op here — never a collection error, never a vacuous pass dressed up
    as coverage. Once the scaffold lands this starts returning real files
    and `test_token_scan_covers_every_present_extension` below is what turns
    that into an enforced non-zero count rather than a silent narrowing.
    """
    if not _FRONTEND_SRC_DIR.is_dir():
        return []
    return [p for p in _FRONTEND_SRC_DIR.rglob("*") if p.is_file() and p.suffix in {".ts", ".tsx"}]


def _template_and_frontend_files() -> list[Path]:
    """`app/templates/*.html` plus `frontend/src`'s `.ts`/`.tsx` files — the
    combined surface the accent-hex and button-composition guards must see
    so neither one goes blind as pages convert."""
    return [*_REPO_ROOT.glob("app/templates/*.html"), *_frontend_src_files()]


def _token_scan_files() -> list[Path]:
    """The exact combined file set this module's token/a11y guards scan:
    app/'s tree (suffix-filtered) plus frontend/src, deduplicated by
    resolved path. This is the input `test_token_scan_covers_every_present_
    extension` measures against a live repo walk below."""
    app_files = (
        p for p in _APP_DIR.rglob("*") if p.is_file() and p.suffix in _SCANNED_SUFFIXES
    )
    combined: dict[Path, Path] = {}
    for p in (*app_files, *_frontend_src_files()):
        combined[p.resolve()] = p
    return list(combined.values())


def test_accent_soft_deleted() -> None:
    """`--accent-soft` appears nowhere under app/ or frontend/src — it was
    deleted, not retinted. Suffix allowlist widened to .ts/.tsx and the scan
    walks frontend/src too, so a future React component cannot quietly
    reintroduce it outside this guard's sight."""
    for path in _token_scan_files():
        contents = path.read_text(errors="ignore")
        assert "accent-soft" not in contents, f"--accent-soft still referenced in {path}"


# ---------------------------------------------------------------------------
# Anti-narrowing pin — the guard must not silently narrow its own scan
# breadth as pages convert. Same idiom as the proof-inventory completeness
# check (scripts/check_proof_inventory.py): counts are measured, never
# hand-pinned, so a future glob edit that drops a suffix reds here instead
# of quietly scanning less.
# ---------------------------------------------------------------------------

_REPO_WALK_SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
)


def _repo_present_suffixes() -> set[str]:
    """Which of the allowlisted suffixes exist anywhere in the live repo
    right now, derived from a real walk — never a hard-coded list — so this
    pin cannot itself go stale. Heavy/irrelevant directories are pruned for
    walk cost only, never for correctness: none of them can hold content
    this guard needs to see."""
    present: set[str] = set()
    for _dirpath, dirnames, filenames in os.walk(_REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _REPO_WALK_SKIP_DIRS]
        for name in filenames:
            suffix = Path(name).suffix
            if suffix in _SCANNED_SUFFIXES:
                present.add(suffix)
    return present


def test_token_scan_covers_every_present_extension() -> None:
    """Anti-narrowing pin: for every allowlisted suffix that genuinely
    exists in the repo right now, the token/a11y scan must have actually
    picked up at least one file of that suffix.

    Once frontend/src exists the .tsx count must be non-zero, and a future
    change that drops an extension from a glob reds here instead of
    silently reducing coverage — the exact blind-spot class a passing guard
    that proves nothing about what it doesn't scan represents.
    """
    scanned_suffixes = {p.suffix for p in _token_scan_files()}
    for suffix in _repo_present_suffixes():
        assert suffix in scanned_suffixes, (
            f"{suffix} files exist in the repo but the token-scan guard "
            f"scanned zero of them — the scan has silently narrowed"
        )


def test_superseded_accent_values_absent() -> None:
    """Neither the superseded accent hexes nor the superseded ring rgba survive."""
    for path in [_STYLE_PATH, *_template_and_frontend_files()]:
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


# ---------------------------------------------------------------------------
# Narrow-width adaptation (group 3b, Task 1f) — parse-level breakpoint guard.
# ---------------------------------------------------------------------------

_NARROW_BREAKPOINT = _extract_media_block(_STYLE_CSS, "max-width: 700px")


def test_narrow_breakpoint_adjusts_shell_and_controls() -> None:
    """The single @media (max-width: 700px) block now reaches the shell inset, the
    inline-form wrap, and both fixed-width selects — not just the two rules
    (conversation heading, disclosure summary) it adjusted before this change."""
    for selector in ("nav", ".page-wrapper", ".form-inline", ".demo-select"):
        assert selector in _NARROW_BREAKPOINT, (
            f"{selector} is not adjusted inside the @media (max-width: 700px) block"
        )
    assert "var(--space-3xl)" not in _NARROW_BREAKPOINT, (
        "the 64px shell-inset token must not survive inside the narrow breakpoint"
    )


# ---------------------------------------------------------------------------
# Muted-ink contrast cluster (group 3b, Task 3a).
# ---------------------------------------------------------------------------


def test_muted_ink_contrast_clears_aa() -> None:
    """Muted ink clears WCAG AA 4.5:1 against every surface it renders on.

    The page-ground pair is the tight one (~4.55:1, clearing AA by 0.05) and is
    what `.lede`, `.form-help`, and `.column-label` all render on at some point
    in the interface. Ratios are recomputed from the live :root block, so this
    gate can never drift from the stylesheet it is guarding.
    """
    ink_muted = _ROOT_TOKENS["--text-muted"]
    bg = _ROOT_TOKENS["--bg"]
    surface = _ROOT_TOKENS["--surface"]
    surface_subtle = _ROOT_TOKENS["--surface-subtle"]

    pairs = {
        "muted-ink-on-page-ground (.lede, .form-help, .column-label)": (ink_muted, bg),
        "muted-ink-on-surface (.form-help, .column-label on a card)": (ink_muted, surface),
        "muted-ink-on-surface-subtle (.column-label in a table header)": (
            ink_muted,
            surface_subtle,
        ),
    }
    for label, (fg, bg_color) in pairs.items():
        ratio = _contrast_ratio(fg, bg_color)
        assert ratio >= 4.5, (
            f"{label}: {fg} on {bg_color} measures {ratio:.2f}:1, below WCAG AA 4.5:1"
        )


# ---------------------------------------------------------------------------
# Button composition (group 3b, Task 3b) — one base, non-cloning modifiers.
# ---------------------------------------------------------------------------

_BUTTON_BASE_PROPERTIES = frozenset(
    {"display", "font-family", "font-size", "font-weight", "cursor", "border-radius", "padding"}
)
_BUTTON_MODIFIERS = (".btn-accent", ".btn-reject", ".btn-retrigger")
# .btn-approve is the money gate: allowlisted by name to override `padding` and
# `font-weight` ONLY — a real visual delta (see the comment beside the rule in
# style.css) so the button that spends money is never the same size as a demo
# trigger. No other base property may appear here either.
_BTN_APPROVE_ALLOWLIST = frozenset({"padding", "font-weight"})


def test_button_modifiers_do_not_redeclare_base_properties() -> None:
    """Each button modifier declares only its color/border deltas, never a base
    `.btn` property. `.btn-approve` is the sole allowlisted exception (padding,
    font-weight — the money gate's real size delta)."""
    for selector in _BUTTON_MODIFIERS:
        declared = _declared_properties(_extract_rule_body(_STYLE_CSS, selector))
        overlap = declared & _BUTTON_BASE_PROPERTIES
        assert not overlap, f"{selector} redeclares base .btn properties: {overlap}"

    approve_declared = _declared_properties(_extract_rule_body(_STYLE_CSS, ".btn-approve"))
    disallowed = (approve_declared & _BUTTON_BASE_PROPERTIES) - _BTN_APPROVE_ALLOWLIST
    assert not disallowed, (
        f".btn-approve redeclares base .btn properties outside its allowlist: {disallowed}"
    )


_BUTTON_MODIFIER_TOKENS = ("btn-accent", "btn-approve", "btn-reject", "btn-retrigger")


def test_button_modifier_classes_always_compose_the_base() -> None:
    """Every template `class` attribute carrying a button modifier also carries the
    bare `btn` base class — the composition rule made enforceable."""
    for path in _template_and_frontend_files():
        html = path.read_text()
        for class_attr in re.findall(r'class="([^"]*)"', html):
            tokens = class_attr.split()
            if any(tok in _BUTTON_MODIFIER_TOKENS for tok in tokens):
                assert "btn" in tokens, (
                    f'{path.name}: class="{class_attr}" carries a button modifier '
                    "without the base 'btn' class"
                )


# ---------------------------------------------------------------------------
# Class hygiene — js- prefix convention.
#
# The presence pin that used to live here
# (`test_script_hook_classes_carry_js_prefix_and_stay_out_of_css`, plus its
# module-scope `runs_list.html` read) is DELETED, not widened. Written
# justification for the deletion follows.
#
# The `js-` convention existed to stop someone deleting a
# `document.querySelector` target (`.js-status-badge`, `.js-failure-summary`,
# `.js-failure-secondary` in the vanilla-JS poller) that looked like dead
# markup because it carried no CSS rule. React holds each of those values in
# component state and re-renders them directly — there is no
# `document.querySelector` call anywhere in a React island, so keeping the
# classNames around after conversion would create the exact thing this
# convention opposed: markup that exists for no live reason. Asserting their
# presence on a page where they no longer do anything would pin dead code,
# not prevent it.
#
# The `/runs` React conversion owns the replacement: a Vitest test asserting
# the status badge updates in place on a new poll result, which is the same
# "the live wiring didn't silently break" property this test used to pin,
# expressed against the layer that now owns it.
#
# This changes what the milestone's own success criteria say about these
# hooks: they no longer "still resolve" or "look like dead markup that would
# break the headline feature if deleted" — that property held for a
# `document.querySelector` poller and no longer holds once the poller's
# target is a React component's state.
#
# The module-scope `runs_list.html` read this test depended on read the file
# at IMPORT time, so renaming or deleting the template took the whole
# module — including the unrelated WCAG contrast gates above — down at
# collection. Deleting the read alongside its sole consumer means collection
# no longer depends on the template's existence at all (verified by
# temporarily renaming the template and confirming `--collect-only` still
# exits 0, then reverting byte-identically).
# ---------------------------------------------------------------------------
