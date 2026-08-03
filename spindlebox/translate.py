"""Body translation: Python source expression -> target-language expression.

This is the first thing in SPIndlebox that converts a *block of code* rather than an
interface (#21). Everything else in `generate/` ports shape and emits `todo!()`.

**The governing rule is: refuse rather than guess.** `translate_body` returns None for
anything outside the provably-safe subset, and the backends then emit exactly the stub
they always did. A wrong translation is far worse than an absent one — a stub fails
loudly at the call site, a mistranslation is a silent defect in ported code. Every
`return None` below is deliberate, not a TODO.

Supported today (Python source only):
  - a single `return <expr>`, optionally preceded by a docstring
  - literals: int, float, bool, str
  - parameter references
  - arithmetic `+ - * %` and floor-division `//`, on operands proven numeric
  - comparisons `< <= > >= == !=`, boolean `and or not`, unary `-`

Deliberately refused, with reasons:
  - `/`      Python's `/` is true division (2/2 -> 1.0); Java and Rust integer-divide.
             Silently wrong for int operands, so it is not attempted at all.
  - `+` on str for Rust  (needs `format!`/`to_string`, not the `+` operator)
  - calls, attributes, subscripts, comprehensions, f-strings, loops, assignments,
             multiple statements, augmented assignment
  - anything whose operand types cannot be proven from the signature

Type proof comes from the item's normalized signature, not from guessing: an expression
is translated only when every leaf resolves to a known core-1 type. That is what makes
the output defensible rather than plausible.
"""

from __future__ import annotations

import ast

from spindlebox.schema import Item

#: Per-target syntax. Kept here rather than in the emit profiles for now because the
#: rules are structural (precedence, division semantics) rather than spellings; move
#: the spellings out to `generate/emit_profiles/*.json` when a third target lands.
_SYNTAX: dict[str, dict] = {
    "rust": {
        "true": "true", "false": "false",
        "and": "&&", "or": "||", "not": "!",
        "floordiv": "/",          # both operands are integers by the time we emit
        "str_concat": None,       # unsupported: Rust `+` needs String + &str
    },
    "java": {
        "true": "true", "false": "false",
        "and": "&&", "or": "||", "not": "!",
        "floordiv": "/",
        "str_concat": "+",        # Java `+` on String is well-defined
    },
}

_NUMERIC = {"i64", "f64"}

_BINOP = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Mod: "%",
}
_CMPOP = {
    ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
    ast.Eq: "==", ast.NotEq: "!=",
}


class _Refused(Exception):
    """Raised the moment anything falls outside the provable subset."""


def _function_def(source: str) -> ast.FunctionDef | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            return node
    return None


class _Translator:
    def __init__(self, param_types: dict[str, str], syntax: dict,
                 rename: dict[str, str] | None = None):
        self.param_types = param_types
        self.syntax = syntax
        # Source name -> emitted identifier. The target escapes reserved words and
        # resolves collisions (Python `final` becomes Java `final_`), so a body that
        # used the source spelling would not compile. Caught by the differential test.
        self.rename = rename or {}

    # each method returns (rendered_text, core1_type)

    def expr(self, node: ast.expr) -> tuple[str, str]:
        if isinstance(node, ast.Constant):
            return self.constant(node)
        if isinstance(node, ast.Name):
            t = self.param_types.get(node.id)
            if t is None:
                raise _Refused(f"name '{node.id}' is not a parameter")
            return self.rename.get(node.id, node.id), t
        if isinstance(node, ast.BinOp):
            return self.binop(node)
        if isinstance(node, ast.UnaryOp):
            return self.unaryop(node)
        if isinstance(node, ast.Compare):
            return self.compare(node)
        if isinstance(node, ast.BoolOp):
            return self.boolop(node)
        raise _Refused(f"unsupported expression {type(node).__name__}")

    def constant(self, node: ast.Constant) -> tuple[str, str]:
        v = node.value
        if isinstance(v, bool):
            return self.syntax["true" if v else "false"], "bool"
        if isinstance(v, int):
            return repr(v), "i64"
        if isinstance(v, float):
            return repr(v), "f64"
        if isinstance(v, str):
            # json-style escaping is correct for both Java and Rust string literals
            import json
            return json.dumps(v), "str"
        raise _Refused(f"unsupported literal {type(v).__name__}")

    def binop(self, node: ast.BinOp) -> tuple[str, str]:
        left, lt = self.expr(node.left)
        right, rt = self.expr(node.right)
        op = type(node.op)

        if op is ast.Div:
            # Python `/` is true division; Java/Rust integer-divide on ints. Refusing
            # is the whole point of this module.
            raise _Refused("'/' has different semantics in the target; refused")

        if op is ast.FloorDiv:
            if lt != "i64" or rt != "i64":
                raise _Refused("'//' only translated for integer operands")
            return f"({left} {self.syntax['floordiv']} {right})", "i64"

        spelling = _BINOP.get(op)
        if spelling is None:
            raise _Refused(f"unsupported operator {op.__name__}")

        if lt == "str" or rt == "str":
            if op is not ast.Add or lt != "str" or rt != "str":
                raise _Refused("only str + str is considered for text")
            concat = self.syntax["str_concat"]
            if concat is None:
                raise _Refused("string concatenation unsupported in this target")
            return f"({left} {concat} {right})", "str"

        if lt not in _NUMERIC or rt not in _NUMERIC:
            raise _Refused(f"arithmetic on non-numeric operands ({lt}, {rt})")
        if op is ast.Mod and (lt == "f64" or rt == "f64"):
            raise _Refused("'%' on floats differs across targets; refused")
        result = "f64" if "f64" in (lt, rt) else "i64"
        return f"({left} {spelling} {right})", result

    def unaryop(self, node: ast.UnaryOp) -> tuple[str, str]:
        operand, t = self.expr(node.operand)
        if isinstance(node.op, ast.USub):
            if t not in _NUMERIC:
                raise _Refused("unary '-' on a non-numeric operand")
            return f"(-{operand})", t
        if isinstance(node.op, ast.Not):
            if t != "bool":
                raise _Refused("'not' on a non-boolean operand")
            return f"({self.syntax['not']}{operand})", "bool"
        raise _Refused(f"unsupported unary {type(node.op).__name__}")

    def compare(self, node: ast.Compare) -> tuple[str, str]:
        if len(node.ops) != 1:
            raise _Refused("chained comparison")   # a < b < c has no direct equivalent
        spelling = _CMPOP.get(type(node.ops[0]))
        if spelling is None:
            raise _Refused(f"unsupported comparison {type(node.ops[0]).__name__}")
        left, lt = self.expr(node.left)
        right, rt = self.expr(node.comparators[0])
        if lt == "str" or rt == "str":
            # Java `==` on String compares identity, not value — a classic silent bug
            raise _Refused("string comparison differs across targets; refused")
        return f"({left} {spelling} {right})", "bool"

    def boolop(self, node: ast.BoolOp) -> tuple[str, str]:
        spelling = self.syntax["and" if isinstance(node.op, ast.And) else "or"]
        parts = []
        for value in node.values:
            rendered, t = self.expr(value)
            if t != "bool":
                raise _Refused("boolean operator on a non-boolean operand")
            parts.append(rendered)
        return "(" + f" {spelling} ".join(parts) + ")", "bool"


def translate_body(item: Item, target: str,
                   rename: dict[str, str] | None = None) -> str | None:
    """Translated body expression for `item` in `target`, or None to keep the stub.

    None is the safe answer and the common one. Callers must treat it as "emit the
    skeleton", never as an error.

    `rename` maps each source parameter name to the identifier the backend actually
    emits. **Backends must pass it.** Targets escape reserved words and resolve
    collisions — Python `final` becomes Java `final_` — so a body rendered with source
    spellings can fail to compile. Omitting it is only safe when no parameter name is
    rewritten, which the caller generally cannot know.
    """
    if item.language != "python" or not item.source_text:
        return None
    syntax = _SYNTAX.get(target)
    if syntax is None:
        return None

    fn = _function_def(item.source_text)
    if fn is None:
        return None

    body = list(fn.body)
    # a leading docstring is not code
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return None

    param_types = {
        p.name: p.norm_type for p in item.signature.params if p.kind != "receiver"
    }
    try:
        rendered, result_type = _Translator(param_types, syntax, rename).expr(body[0].value)
    except _Refused:
        return None
    except RecursionError:                       # pathological nesting
        return None

    # the translated expression must actually produce the declared return type
    if result_type != item.signature.returns_norm:
        return None
    return rendered
