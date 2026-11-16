"""Safe arithmetic evaluator for the agent's `calculate` tool.

The LLM never does arithmetic itself. It passes an expression here and gets an exact result.
Parsing uses `ast` (never `eval`) and only a small whitelist of node types is allowed.
All math is done with `Decimal` to avoid float noise.
"""

import ast
import operator
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext

MAX_EXPR_LEN = 500
MAX_EXPONENT = 100
MAX_ABS_VALUE = Decimal("1e30")


class CalcError(ValueError):
    """Raised for any expression that is invalid, unsafe, or cannot be evaluated."""


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _round(x: Decimal, ndigits: Decimal = Decimal(0)) -> Decimal:
    n = int(ndigits)
    return round(x, n) if n > 0 else Decimal(round(x, n))


_FUNCS = {"round": _round, "abs": abs, "min": min, "max": max}


def _eval(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise CalcError("Only numeric constants are allowed.")
        return Decimal(str(node.value))
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            if right != right.to_integral_value() or abs(right) > MAX_EXPONENT:
                raise CalcError(f"Exponent must be an integer with |n| <= {MAX_EXPONENT}.")
            result = left ** int(right)
        elif type(node.op) in _BINOPS:
            result = _BINOPS[type(node.op)](left, right)
        else:
            raise CalcError(f"Operator {type(node.op).__name__} is not allowed.")
        if abs(result) > MAX_ABS_VALUE:
            raise CalcError("Result is too large.")
        return result
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS or node.keywords:
            raise CalcError("Only round, abs, min, max may be called.")
        args = [_eval(a) for a in node.args]
        if not args:
            raise CalcError(f"{node.func.id}() needs arguments.")
        return _FUNCS[node.func.id](*args)
    raise CalcError(f"Unsupported expression element: {type(node).__name__}.")


def calculate(expression: str) -> Decimal:
    """Evaluate an arithmetic expression exactly. Raises CalcError on anything unsafe or invalid."""
    if not isinstance(expression, str) or not expression.strip():
        raise CalcError("Expression is empty.")
    if len(expression) > MAX_EXPR_LEN:
        raise CalcError(f"Expression longer than {MAX_EXPR_LEN} characters.")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise CalcError(f"Invalid expression: {e.msg}") from e
    try:
        with localcontext() as ctx:
            ctx.prec = 28
            return _eval(tree.body)
    except (DivisionByZero, ZeroDivisionError) as e:
        raise CalcError("Division by zero.") from e
    except InvalidOperation as e:
        raise CalcError("Invalid arithmetic operation.") from e
    except (TypeError, ValueError) as e:
        if isinstance(e, CalcError):
            raise
        raise CalcError(f"Invalid arguments: {e}") from e
