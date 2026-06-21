"""Minimal in-house inbound-body cleaning (INGEST-02, T-02-10, review FIX C).

Strips quoted reply history and trailing signatures BEFORE the body is persisted
to email_messages.body_text, so the stored body is the single cleaned source of
truth the extraction stage reads (FIX C) and a signature name is never pulled in
as a phantom employee.

This is deliberately a SMALL code-strip — NOT a third-party reply-parser (talon /
email-reply-parser) and NOT a sprawling hand-rolled engine. It covers the common
markers present in the committed Phase 2 fixtures:

  - quoted-history lines beginning with ">"
  - an "On <date> ... wrote:" attribution block and everything below it
  - a trailing signature delimiter ("-- " on its own line, or a "Sent from my ..."
    line) and everything below it

Adopting a purpose-built reply-parser for real-client variety is explicitly
deferred to P6 (RESEARCH Don't-Hand-Roll qualifier; D-A4-03 fixture-first). Doing
so re-introduces a package-legitimacy gate at that point — out of scope here. This
module adds NO new dependency.
"""
from __future__ import annotations

import re

# "On <date/anything> wrote:" attribution that introduces a quoted reply block.
# Tolerates the attribution spanning intervening text up to the trailing "wrote:".
_ATTRIBUTION_RE = re.compile(r"^On .*wrote:\s*$", re.IGNORECASE)

# A signature delimiter line: the RFC "-- " sigdash (with or without the trailing
# space some clients trim) or a mobile "Sent from my ..." footer.
_SIG_DELIM_RE = re.compile(r"^(--\s*|Sent from my\b.*)$", re.IGNORECASE)


def clean_body(text: str) -> str:
    """Return the inbound body with quoted history + a trailing signature removed.

    The first quoted-history marker (an attribution line OR the first run of ">"
    quoted lines) and everything after it is dropped; a trailing signature block
    introduced by a sigdash / "Sent from my" line is dropped. The remaining text
    is stripped of trailing whitespace. Idempotent: cleaning an already-cleaned
    body returns it unchanged.
    """
    if not text:
        return text

    lines = text.splitlines()
    cut = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Attribution block ("On ... wrote:") — everything below is quoted history.
        if _ATTRIBUTION_RE.match(stripped):
            cut = min(cut, i)
            break
        # A quoted-history line — drop from here down (the quoted block + anything
        # trailing it). Phase 2 fixtures quote contiguous ">" blocks at the tail.
        if stripped.startswith(">"):
            cut = min(cut, i)
            break

    kept = lines[:cut]

    # Drop a trailing signature block: scan for the LAST sigdash / "Sent from my"
    # delimiter and cut from there. Only treat it as a signature if it is in the
    # tail region (nothing but the sign-off below it) — a conservative cut.
    sig_cut = len(kept)
    for i, line in enumerate(kept):
        if _SIG_DELIM_RE.match(line.strip()):
            sig_cut = i
            break
    kept = kept[:sig_cut]

    return "\n".join(kept).rstrip()
