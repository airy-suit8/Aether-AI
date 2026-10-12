"""
agents/tools.py — LangChain Tools for the Aether AI Knowledge Assistant Agent
Task 9:  Calculator Tool (safe math evaluation via AST)
Task 10: Date-Time Tool (current date/time, day computations, done in Python)
"""

import ast
import operator
import math
import re
from datetime import date, datetime, timedelta

from langchain_core.tools import tool


# ── Task 9: Calculator Tool ──────────────────────────────────────────────────

# Largest power result the calculator will compute, in bits (about 3,000 decimal digits).
# Without a cap, "9**9**9" never finishes and holds the GIL.
MAX_POWER_BITS = 10_000


def _checked_pow(base, exponent):
    """Power with a size cap on integer results."""
    if isinstance(base, int) and isinstance(exponent, int) and abs(base) > 1:
        if base.bit_length() * abs(exponent) > MAX_POWER_BITS:
            raise ValueError("Result too large to compute")
    return operator.pow(base, exponent)


# Allowed operators for safe math evaluation
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _checked_pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Safe math functions the calculator can use
_SAFE_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "pi": math.pi,
    "e": math.e,
}


def _safe_eval_node(node):
    """Recursively evaluate an AST node with only safe math operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value}")
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        return _SAFE_OPERATORS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        operand = _safe_eval_node(node.operand)
        return _SAFE_OPERATORS[op_type](operand)
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _SAFE_FUNCTIONS:
            func = _SAFE_FUNCTIONS[node.func.id]
            args = [_safe_eval_node(arg) for arg in node.args]
            if callable(func):
                return func(*args)
            return func  # For constants like pi, e
        raise ValueError(f"Unsupported function: {getattr(node.func, 'id', 'unknown')}")
    elif isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCTIONS:
            val = _SAFE_FUNCTIONS[node.id]
            if not callable(val):
                return val  # Constants like pi, e
        raise ValueError(f"Unknown variable: {node.id}")
    else:
        raise ValueError(f"Unsupported expression type: {type(node).__name__}")


@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression safely. Supports +, -, *, /, **, %, sqrt(), abs(), round(), sin(), cos(), tan(), log(), log10(), pi, e.
    
    Examples: "45 * 78", "sqrt(144)", "2 ** 10", "(15 + 25) / 4"
    """
    try:
        # Clean expression
        expr = expression.strip()
        # Replace common math symbols
        expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**")
        # "3 x 4" or "3x4" means multiply; the x in a name like max() is left alone
        expr = re.sub(r"(?<=[\d.)\s])[xX](?=[\s\d.(])", "*", expr)
        
        # Parse and safely evaluate
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval_node(tree)
        
        # Format nicely: 15 significant digits hides float noise (0.1 + 0.2) without rounding real digits
        if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
            return f"{expression} = {int(result)}"
        elif isinstance(result, float):
            return f"{expression} = {result:.15g}"
        return f"{expression} = {result}"
    except ZeroDivisionError:
        return "Error: Division by zero."
    except Exception as e:
        return f"Error evaluating '{expression}': {str(e)}"


# ── Task 10: Date-Time Tool ──────────────────────────────────────────────────
# The arithmetic is done here, in Python. The tool used to hand the question and the current
# time to the model and return whatever it worked out (R11).

DATE_OPERATIONS = ("now", "weekday", "days_between", "add_days")


def _now() -> datetime:
    return datetime.now()


def _date(text: str, today: date) -> date:
    """A YYYY-MM-DD date; empty, "today" or "now" is today."""
    text = (text or "").strip().lower()
    if text in ("", "today", "now"):
        return today
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"'{text}' is not a date. Write dates as YYYY-MM-DD, for example 2026-12-31.") from None


def _long(day: date) -> str:
    return f"{day:%A}, {day.day} {day:%B %Y}"


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


@tool
def datetime_tool(operation: str = "now", start: str = "", end: str = "", days: int = 0) -> str:
    """Date and time facts, computed exactly. Dates are written YYYY-MM-DD; an empty date means today.

    operation:
      "now"           the current date, weekday and time
      "weekday"       the weekday of `start`
      "days_between"  the number of days from `start` to `end`
      "add_days"      the date `days` days after `start` (a negative number goes back)
    """
    now = _now()
    try:
        if operation == "now":
            return f"Today is {_long(now.date())}. The time is {now:%H:%M}."
        if operation == "weekday":
            return f"{_date(start, now.date()).isoformat()} is a {_date(start, now.date()):%A}."
        if operation == "days_between":
            first, second = _date(start, now.date()), _date(end, now.date())
            count = (second - first).days
            if count < 0:
                return f"{second.isoformat()} is {_days(-count)} before {first.isoformat()}."
            return f"From {first.isoformat()} to {second.isoformat()} is {_days(count)}."
        if operation == "add_days":
            first = _date(start, now.date())
            result = first + timedelta(days=days)
            direction = f"{_days(days)} after" if days >= 0 else f"{_days(-days)} before"
            return f"{direction} {first.isoformat()} is {_long(result)} ({result.isoformat()})."
    except (ValueError, OverflowError) as e:
        return f"Error: {e}"
    return f"Error: unknown operation '{operation}'. Use one of: {', '.join(DATE_OPERATIONS)}."


# ── Tool Registry ────────────────────────────────────────────────────────────

ALL_TOOLS = [calculator, datetime_tool]
