"""CJK-aware tokenizer shared by BM25 and the lexical rerank features.

Latin/digit runs become lowercase word tokens; each CJK character becomes a
unigram and consecutive CJK characters additionally form bigrams, which is
the standard lightweight treatment for Chinese full-text retrieval without
requiring a dictionary segmenter.
"""

import re

_LATIN_RUN = re.compile(r"[a-z0-9][a-z0-9_.\-+/]*")
_CJK_RUN = re.compile(r"[一-鿿㐀-䶿]+")


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens: list[str] = []

    for match in _LATIN_RUN.finditer(lowered):
        token = match.group(0).strip("_.-+/")
        if token:
            tokens.append(token)

    for run_match in _CJK_RUN.finditer(text):
        run = run_match.group(0)
        tokens.extend(list(run))
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))

    return tokens
