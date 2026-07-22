from findexer.depmap import external_packages, find_env_vars, resolve_calls


def test_env_vars_python():
    body = (
        'a = os.environ["FOO"]\n'
        "b = os.environ.get('BAR')\n"
        'c = os.getenv("BAZ", "x")\n'
    )
    assert find_env_vars(body, "python") == ["BAR", "BAZ", "FOO"]


def test_env_vars_js():
    body = 'const a = process.env.API_KEY; const b = process.env["OTHER"];'
    assert find_env_vars(body, "javascript") == ["API_KEY", "OTHER"]


def test_env_vars_go():
    body = 'v := os.Getenv("HOME_DIR")\nw, ok := os.LookupEnv("PORT")'
    assert find_env_vars(body, "go") == ["HOME_DIR", "PORT"]


def test_env_vars_rust():
    body = 'let v = std::env::var("RUST_LOG").unwrap();'
    assert find_env_vars(body, "rust") == ["RUST_LOG"]


def test_env_vars_bash():
    body = 'echo "$MY_TARGET" && cp x "${DEST_DIR}/y"\nlocal lower=$foo'
    assert find_env_vars(body, "bash") == ["DEST_DIR", "MY_TARGET"]


def test_external_packages_python():
    ext = external_packages(["json", "os", "requests", "util.io"], "python", {"util", "app"})
    assert ext == ["requests"]


def test_external_packages_js():
    ext = external_packages(
        ["./local", "../other", "react", "@scope/pkg/sub", "node:fs"], "javascript", set()
    )
    assert ext == ["@scope/pkg", "react"]


def test_external_packages_go():
    ext = external_packages(
        ["fmt", "os", "github.com/pkg/errors", "myapp/internal"], "go", {"myapp"}
    )
    assert ext == ["github.com/pkg/errors"]


def test_external_packages_rust():
    ext = external_packages(
        ["std::fs", "crate::util", "serde_json::Value", "super::x"], "rust", set()
    )
    assert ext == ["serde_json"]


def test_resolve_calls():
    # items: mod1.f (ordinal irrelevant), mod2.g, two items named dup in different modules
    addr_by_name = {
        "f": ["mod1.f"],
        "g": ["mod2.g"],
        "dup": ["mod1.dup", "mod2.dup"],
    }
    resolved = resolve_calls(
        raw_calls=["f", "g", "dup", "json.loads"],
        caller_group="mod1",
        addresses_by_name=addr_by_name,
    )
    assert "mod1.f" in resolved            # same-module wins
    assert "mod2.g" in resolved            # unique global name
    assert "mod1.dup" in resolved          # ambiguous → same-module match
    assert "external:json.loads" in resolved
