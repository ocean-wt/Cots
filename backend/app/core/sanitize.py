"""Input hardening helpers."""

import unicodedata

# Strip C0/C1 control characters except the common whitespace ones.
_KEEP_CONTROLS = {"\n", "\r", "\t"}


def clean_text(value: str, max_len: int) -> str:
    """Normalize unicode and remove control characters / excessive spaces."""
    value = unicodedata.normalize("NFC", value)
    cleaned = "".join(
        ch for ch in value
        if ch in _KEEP_CONTROLS or unicodedata.category(ch)[0] != "C"
    )
    # collapse runs of blank lines / spaces that could abuse UI rendering
    lines = [line.rstrip() for line in cleaned.splitlines()]
    cleaned = "\n".join(lines)
    return cleaned[:max_len]
