"""The small expression language of the KPI config.

Row expressions (a KPI's `column`, a filter's `column`) are compiled to SQL over one telemetry row:
    names       telemetry columns of the domain (system_telemetry, pcs_telemetry), global params (`params:`),
                entity params (`system_params:`)
    operators   + - * /  (division by zero gives NULL), unary -, parentheses, numbers
    functions   abs(x), sqrt(x) (NULL for x < 0), greatest(a, b, ...), least(a, b, ...),
                delta(x) = x minus the previous sample's x (same system / PCS unit)

Formulas (derived KPIs) are evaluated in Python over KPI codes and params, with + - * / and abs(), sqrt(),
greatest(), least().
Anything else (attribute access, other calls, strings, comparisons) is rejected at load time.
"""
import ast
from typing import Callable, Optional

ROW_FUNCS = {"abs", "delta", "sqrt", "greatest", "least"}
FORMULA_FUNCS = {"abs", "sqrt", "greatest", "least"}
MULTI_ARG = {"greatest", "least"}  # two or more arguments; the others take exactly one

_BASE_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant, ast.Call,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)


class ExprError(Exception):
    pass


def parse(src: str, funcs: set[str]) -> ast.Expression:
    """Parse and check an expression; returns the tree."""
    try:
        tree = ast.parse(str(src), mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"'{src}' is not a valid expression: {exc.msg}")
    for node in ast.walk(tree):
        if not isinstance(node, _BASE_NODES):
            raise ExprError(f"'{src}' may only use + - * / ( ), numbers, names and {', '.join(sorted(funcs))}()")
        if isinstance(node, ast.Constant) and (isinstance(node.value, bool) or not isinstance(node.value, (int, float))):
            raise ExprError(f"'{src}' has a non-numeric constant")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in funcs:
                raise ExprError(f"'{src}': only {', '.join(sorted(funcs))}() can be called")
            if node.keywords:
                raise ExprError(f"'{src}': {node.func.id}() takes no keyword arguments")
            if node.func.id in MULTI_ARG:
                if len(node.args) < 2:
                    raise ExprError(f"'{src}': {node.func.id}() takes two or more arguments")
            elif len(node.args) != 1:
                raise ExprError(f"'{src}': {node.func.id}() takes exactly one argument")
    return tree


def names(src: str, funcs: set[str]) -> set[str]:
    tree = parse(src, funcs)
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - called


def to_sql(src: str, resolve: Callable[[str], str], entity_col: str = "system_id") -> str:
    """Compile a row expression to SQL; `resolve` maps a name to its SQL (column, bind or system param).
    entity_col is the telemetry column delta() partitions by (system_id, pcs_id)."""
    tree = parse(src, ROW_FUNCS)

    def sql(node) -> str:
        if isinstance(node, ast.Expression):
            return sql(node.body)
        if isinstance(node, ast.Constant):
            return f"CAST({float(node.value)!r} AS numeric)"
        if isinstance(node, ast.Name):
            return resolve(node.id)
        if isinstance(node, ast.UnaryOp):
            return f"(-{sql(node.operand)})" if isinstance(node.op, ast.USub) else sql(node.operand)
        if isinstance(node, ast.Call):
            fn = node.func.id
            if fn in MULTI_ARG:
                # GREATEST / LEAST ignore NULLs in PostgreSQL; a NULL input should give NULL like the other operators
                args = [sql(a) for a in node.args]
                nulls = " OR ".join(f"{a} IS NULL" for a in args)
                return f"(CASE WHEN {nulls} THEN NULL ELSE {fn.upper()}({', '.join(args)}) END)"
            inner = sql(node.args[0])
            if fn == "abs":
                return f"ABS({inner})"
            if fn == "sqrt":
                return f"(CASE WHEN {inner} >= 0 THEN SQRT({inner}) END)"
            return f'({inner} - LAG({inner}) OVER (PARTITION BY t."{entity_col}" ORDER BY t.ts))'
        a, b = sql(node.left), sql(node.right)
        if isinstance(node.op, ast.Add):
            return f"({a} + {b})"
        if isinstance(node.op, ast.Sub):
            return f"({a} - {b})"
        if isinstance(node.op, ast.Mult):
            return f"({a} * {b})"
        return f"({a} / NULLIF({b}, 0))"

    return sql(tree)


def evaluate(src: str, values: dict[str, Optional[float]]) -> Optional[float]:
    """Evaluate a formula; a missing input or a division by zero gives None."""
    tree = parse(src, FORMULA_FUNCS)

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            v = values.get(node.id)
            return None if v is None else float(v)
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            return None if v is None else (-v if isinstance(node.op, ast.USub) else v)
        if isinstance(node, ast.Call):
            args = [ev(a) for a in node.args]
            if any(a is None for a in args):
                return None
            fn = node.func.id
            if fn == "greatest":
                return max(args)
            if fn == "least":
                return min(args)
            if fn == "sqrt":
                return None if args[0] < 0 else args[0] ** 0.5
            return abs(args[0])
        a, b = ev(node.left), ev(node.right)
        if a is None or b is None:
            return None
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        return None if b == 0 else a / b

    return ev(tree)
