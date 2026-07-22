from findexer.schema import Param, Signature
from findexer.sigclass import sig_class_id
from findexer.typenorm import normalize


def sig(params, ret):
    return Signature(
        params=[Param(name=n, raw_type=None, norm_type=t, default=None, kind=k) for n, t, k in params],
        returns_raw=None,
        returns_norm=ret,
    )


def test_basic():
    s = sig([("path", "str", "positional")], "list<str>")
    assert sig_class_id(s) == "sig:str->list<str>"


def test_receiver_excluded():
    s = sig([("self", "any", "receiver"), ("x", "i64", "positional")], "i64")
    assert sig_class_id(s) == "sig:i64->i64"


def test_variadic_marked():
    s = sig([("args", "list<str>", "variadic")], "unit")
    assert sig_class_id(s) == "sig:*list<str>->unit"


def test_kwvariadic_excluded():
    s = sig([("x", "str", "positional"), ("kw", "map<str,any>", "kwvariadic")], "unit")
    assert sig_class_id(s) == "sig:str->unit"


def test_no_params():
    assert sig_class_id(sig([], "unit")) == "sig:->unit"


def test_cross_language_same_class():
    """Python def f(p: str) -> list[str] and Go func F(p string) []string share a class."""
    py = sig([("p", normalize("str", "python"), "positional")], normalize("list[str]", "python"))
    go = sig([("p", normalize("string", "go"), "positional")], normalize("[]string", "go"))
    assert sig_class_id(py) == sig_class_id(go)
