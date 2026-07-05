from __future__ import annotations


def normalize_uploaded_filename(filename: str | None, fallback: str = "video") -> str:
    value = (filename or fallback).strip() or fallback
    value = value.replace("\\", "/").rsplit("/", 1)[-1] or fallback
    repaired = _repair_mojibake_filename(value)
    return repaired or fallback


def _repair_mojibake_filename(filename: str) -> str:
    best = filename
    best_score = _filename_readability_score(filename)
    for source_encoding in ("latin1", "cp1252"):
        try:
            candidate = filename.encode(source_encoding).decode("utf-8")
        except UnicodeError:
            continue
        score = _filename_readability_score(candidate)
        if score > best_score + 3:
            best = candidate
            best_score = score
    return best


def _filename_readability_score(value: str) -> int:
    score = 0
    for char in value:
        code = ord(char)
        if char == "\ufffd" or code < 32 or 0x7F <= code < 0xA0:
            score -= 12
        elif "\u4e00" <= char <= "\u9fff":
            score += 4
        elif char.isprintable():
            score += 1
        else:
            score -= 2
    for marker in ("Ã", "Â", "â", "ç", "å", "è", "ï", "¼", "½"):
        score -= value.count(marker) * 3
    return score
