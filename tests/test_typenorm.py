import pytest

from spindlebox.typenorm import go_return, normalize

PY_CASES = [
    ("str", "str"),
    ("int", "i64"),
    ("float", "f64"),
    ("bool", "bool"),
    ("bytes", "bytes"),
    ("None", "unit"),
    (None, "any"),
    ("", "any"),
    ("Any", "any"),
    ("list[str]", "list<str>"),
    ("List[str]", "list<str>"),
    ("dict[str, int]", "map<str,i64>"),
    ("Dict[str, int]", "map<str,i64>"),
    ("set[int]", "set<i64>"),
    ("tuple[str, int]", "tuple<str,i64>"),
    ("Optional[str]", "option<str>"),
    ("Union[str, None]", "option<str>"),
    ("str | None", "option<str>"),
    ("Optional[List[str]]", "option<list<str>>"),
    ("Union[int, str]", "any"),
    ("Iterator[str]", "iter<str>"),
    ("Iterable[int]", "iter<i64>"),
    ("Callable[[int], str]", "fn"),
    ("Path", "obj:Path"),
    ("list[Path]", "list<obj:Path>"),
]

TS_CASES = [
    ("string", "str"),
    ("number", "f64"),
    ("boolean", "bool"),
    ("void", "unit"),
    ("any", "any"),
    ("unknown", "any"),
    (None, "any"),
    ("string[]", "list<str>"),
    ("Array<string>", "list<str>"),
    ("Record<string, number>", "map<str,f64>"),
    ("Map<string, number>", "map<str,f64>"),
    ("Set<number>", "set<f64>"),
    ("string | null", "option<str>"),
    ("string | undefined", "option<str>"),
    ("Promise<string>", "str"),
    ("Promise<void>", "unit"),
    ("Foo", "obj:Foo"),
    ("string | number", "any"),
]

GO_CASES = [
    ("string", "str"),
    ("int", "i64"),
    ("int64", "i64"),
    ("uint32", "i64"),
    ("float64", "f64"),
    ("bool", "bool"),
    ("[]byte", "bytes"),
    ("[]string", "list<str>"),
    ("map[string]int", "map<str,i64>"),
    ("error", "error"),
    ("*Foo", "obj:Foo"),
    ("interface{}", "any"),
    ("any", "any"),
    (None, "unit"),
]

RUST_CASES = [
    ("String", "str"),
    ("&str", "str"),
    ("i32", "i64"),
    ("usize", "i64"),
    ("f32", "f64"),
    ("bool", "bool"),
    ("()", "unit"),
    (None, "unit"),
    ("Vec<String>", "list<str>"),
    ("HashMap<String, i64>", "map<str,i64>"),
    ("HashSet<u8>", "set<i64>"),
    ("Option<String>", "option<str>"),
    ("Result<String, io::Error>", "result<str,obj:io::Error>"),
    ("&mut Vec<u8>", "list<i64>"),
    ("Box<dyn Fn(i32) -> i32>", "fn"),
    ("impl Iterator<Item = u8>", "obj:Iterator"),
    ("Foo", "obj:Foo"),
]


@pytest.mark.parametrize("raw,expected", PY_CASES)
def test_python(raw, expected):
    assert normalize(raw, "python") == expected


@pytest.mark.parametrize("raw,expected", TS_CASES)
def test_typescript(raw, expected):
    assert normalize(raw, "typescript") == expected


@pytest.mark.parametrize("raw,expected", GO_CASES)
def test_go(raw, expected):
    assert normalize(raw, "go") == expected


@pytest.mark.parametrize("raw,expected", RUST_CASES)
def test_rust(raw, expected):
    assert normalize(raw, "rust") == expected


def test_js_defaults_to_any():
    assert normalize(None, "javascript") == "any"


def test_go_multi_return():
    assert go_return(["string", "error"]) == "result<str,error>"
    assert go_return(["int", "string"]) == "tuple<i64,str>"
    assert go_return(["string"]) == "str"
    assert go_return([]) == "unit"


def test_cross_language_agreement():
    """The whole point: same shape in different languages → same norm type."""
    assert normalize("list[str]", "python") == normalize("string[]", "typescript")
    assert normalize("list[str]", "python") == normalize("[]string", "go")
    assert normalize("list[str]", "python") == normalize("Vec<String>", "rust")


def test_multiline_type_collapses_to_single_line():
    """Real Rust tuple types span lines with trailing commas (memchr #6);
    normalization must not emit newlines into downstream code."""
    raw = "(\n  usize,\n  SearchBound<&'r Q>,\n)"
    result = normalize(raw, "rust")
    assert "\n" not in result
    assert "obj:" not in result or all(" " not in seg for seg in result.split(","))


def test_java_table_driven():
    """Java normalizes through its profile's type table — no _java() function."""
    assert normalize("String", "java") == "str"
    assert normalize("int", "java") == "i64"
    assert normalize("double", "java") == "f64"
    assert normalize("boolean", "java") == "bool"
    assert normalize("void", "java") == "unit"
    assert normalize("byte[]", "java") == "bytes"
    assert normalize("String[]", "java") == "list<str>"
    assert normalize("List<String>", "java") == "list<str>"
    assert normalize("java.util.List<String>", "java") == "list<str>"
    assert normalize("Map<String, Integer>", "java") == "map<str,i64>"
    assert normalize("Optional<Map<String, Integer>>", "java") == "option<map<str,i64>>"
    assert normalize("Function<String, Integer>", "java") == "fn"
    assert normalize("Stream<String>", "java") == "iter<str>"
    assert normalize("CompletableFuture<String>", "java") == "str"
    assert normalize("Widget", "java") == "obj:Widget"
    assert normalize(None, "java") == "unit"
    assert normalize("list[str]", "python") == normalize("List<String>", "java")
