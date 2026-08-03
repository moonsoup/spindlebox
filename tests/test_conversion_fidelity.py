"""Characterization tests for cross-language conversion fidelity (audit 2026-08-03).

Intended path: tests/test_conversion_fidelity.py

These pin the CURRENT behaviour of `typenorm.normalize` at the points where two
distinct source types collapse into one core-1 type. Each collapse is a place where
converting A -> B cannot recover the original type.

They are deliberately written as characterization tests, not as failing bug reports:
a green run CONFIRMS the audit's static reading, and a fix to any finding will flip
exactly one test, forcing the change to be deliberate rather than silent.

Every assertion here was derived by reading spindlebox/typenorm.py without executing
it (the audit session had no execution). A failure means the audit misread the code —
that is a useful result, and the reason these exist.

Findings: CONV-05 .. CONV-09.
"""

from __future__ import annotations

from spindlebox.typenorm import normalize

# --------------------------------------------------------------- CONV-05


def test_rust_unsigned_and_signed_collapse_to_one_type():
    """u64 and i64 are indistinguishable after normalization (typenorm.py:216-219, 272-273).

    Consequence: Rust `u64` -> Java `long` silently changes the value domain; a value
    above i64::MAX is unrepresentable and nothing reports the loss.
    """
    assert normalize("u64", "rust") == "i64"
    assert normalize("i64", "rust") == "i64"
    assert normalize("u64", "rust") == normalize("i64", "rust")


def test_rust_integer_widths_all_collapse():
    """Every width in _RUST_INT maps to i64 — u8 and i128 are the same type downstream."""
    for spelling in ("u8", "u16", "u32", "u128", "usize", "i8", "i128", "isize"):
        assert normalize(spelling, "rust") == "i64", spelling


def test_go_unsigned_collapses_to_signed():
    """_GO_INT folds uint64/uintptr into i64 (typenorm.py:152-155, 188-189)."""
    assert normalize("uint64", "go") == "i64"
    assert normalize("uint64", "go") == normalize("int64", "go")


# --------------------------------------------------------------- CONV-06


def test_two_arm_optional_is_preserved():
    """The one union shape that survives: T | None -> option<T> (typenorm.py:68-69)."""
    assert normalize("str | None", "python") == "option<str>"
    assert normalize("Optional[str]", "python") == "option<str>"


def test_three_arm_union_loses_all_type_information():
    """More than two arms -> `any` (typenorm.py:70, 92). Ordinary Python/TS shape."""
    assert normalize("str | int | None", "python") == "any"
    assert normalize("Union[str, int, bool]", "python") == "any"


def test_typescript_multi_arm_union_also_collapses():
    """Same collapse on the TS side (typenorm.py:126)."""
    assert normalize("string | number | boolean", "typescript") == "any"


# --------------------------------------------------------------- CONV-07


def test_go_channel_is_erased_to_any():
    """`chan T` -> "obj:chan T" (typenorm.py:196-197), whose space fails the core-1
    grammar guard (_CORE1_ALLOWED, :367-371), so normalize returns "any" (:395).

    The erasure is a side effect of the grammar guard rather than a decision, and had
    no test before this one. A Go concurrency signature is indistinguishable from an
    untyped one after indexing.
    """
    assert normalize("chan string", "go") == "any"
    assert normalize("chan string", "go") == normalize("interface{}", "go")


def test_directional_channels_also_erased():
    assert normalize("<-chan int", "go") == "any"
    assert normalize("chan<- int", "go") == "any"


# --------------------------------------------------------------- CONV-08


def test_rust_borrow_and_mutability_are_stripped():
    """&mut T, &T and T are identical after normalization (typenorm.py:229-237).

    For a tool whose stated purpose is migration *to* Rust, ownership and mutability
    are the highest-value facts to carry across, and they are discarded first.
    """
    owned = normalize("Vec<String>", "rust")
    assert normalize("&mut Vec<String>", "rust") == owned
    assert normalize("&Vec<String>", "rust") == owned
    assert owned == "list<str>"


# --------------------------------------------------------------- CONV-09


def test_python_int_and_typescript_number_disagree():
    """int -> i64 (typenorm.py:45) but number -> f64 (:109), so the same function in
    Python and TypeScript lands in a DIFFERENT sig_class.

    This is the gap that survives a green suite: test_typenorm.py's
    test_cross_language_agreement covers list[str] only, never a numeric.
    """
    assert normalize("int", "python") == "i64"
    assert normalize("number", "typescript") == "f64"
    assert normalize("int", "python") != normalize("number", "typescript")


def test_the_agreement_that_does_hold_still_holds():
    """Guard rail: the documented cross-language agreement must not regress while
    the numeric disagreement above is being addressed."""
    py = normalize("list[str]", "python")
    assert py == normalize("string[]", "typescript")
    assert py == normalize("[]string", "go")
    assert py == normalize("Vec<String>", "rust")
    assert py == normalize("List<String>", "java")


# --------------------------------------------------------------- minor, noted not filed


def test_bytearray_loses_mutability_and_f32_widens():
    assert normalize("bytearray", "python") == normalize("bytes", "python") == "bytes"
    assert normalize("f32", "rust") == normalize("f64", "rust") == "f64"
