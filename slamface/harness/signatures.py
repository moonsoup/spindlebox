"""Error-signature hashing — the single identity module shared by container and local sides.

A signature identifies a failure MODE, not a failure instance: same stage, same
exception class, same code location (path-relativized, line-stripped), same language
→ same 12-hex signature, regardless of message text, absolute paths, or line drift
within a function.
"""

from __future__ import annotations

import hashlib
import re

_LINE_NO = re.compile(r":\d+")
_ROOT_MARKERS = ("/app/", "site-packages/", "/Software/spindlebox/", "/spindlebox/spindlebox/")


def normalize_trace_head(trace_head: str) -> str:
    """'/app/spindlebox/generate/rust_backend.py:87 in emit_op_array'
    → 'spindlebox/generate/rust_backend.py in emit_op_array'."""
    s = _LINE_NO.sub("", trace_head.strip())
    for marker in _ROOT_MARKERS:
        idx = s.find(marker)
        if idx != -1:
            s = s[idx + len(marker):]
            break
    else:
        # unknown prefix: keep at most the last 3 path components
        m = re.match(r"(\S+)(.*)", s)
        if m and "/" in m.group(1):
            parts = m.group(1).split("/")
            s = "/".join(parts[-3:]) + m.group(2)
    return s.strip()


def error_signature(stage: str, error_class: str, trace_head: str, lang: str) -> str:
    normalized = normalize_trace_head(trace_head)
    digest = hashlib.sha256(f"{stage}|{error_class}|{normalized}|{lang}".encode()).hexdigest()
    return digest[:12]
