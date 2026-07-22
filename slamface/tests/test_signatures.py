from slamface.harness.signatures import error_signature, normalize_trace_head


def test_line_numbers_stripped():
    a = normalize_trace_head("spindlebox/generate/rust_backend.py:87 in emit_op_array")
    b = normalize_trace_head("spindlebox/generate/rust_backend.py:91 in emit_op_array")
    assert a == b


def test_path_prefixes_relativized():
    container = "/app/spindlebox/generate/rust_backend.py:87 in emit_op_array"
    local = "/Users/isme/Software/spindlebox/spindlebox/generate/rust_backend.py:87 in emit_op_array"
    assert normalize_trace_head(container) == normalize_trace_head(local)


def test_signature_stable_across_environments():
    s1 = error_signature("generate_rust", "KeyError",
                         "/app/spindlebox/generate/rust_backend.py:87 in emit_op_array", "python")
    s2 = error_signature("generate_rust", "KeyError",
                         "/Users/isme/Software/spindlebox/spindlebox/generate/rust_backend.py:99 in emit_op_array",
                         "python")
    assert s1 == s2
    assert len(s1) == 12


def test_signature_distinguishes_modes():
    base = ("generate_rust", "KeyError", "spindlebox/x.py in f", "python")
    assert error_signature(*base) != error_signature("index", *base[1:])
    assert error_signature(*base) != error_signature(base[0], "TypeError", *base[2:])
    assert error_signature(*base) != error_signature(*base[:3], "go")


def test_unknown_prefix_keeps_tail():
    s = normalize_trace_head("/some/random/venv/lib/python3.11/foo/bar/baz.py:12 in qux")
    assert s == "foo/bar/baz.py in qux"
