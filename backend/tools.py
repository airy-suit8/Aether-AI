"""
tools.py — LangChain Tools for the Aether AI Knowledge Assistant Agent
Task 9:  Calculator Tool (safe math evaluation via AST)
Task 10: Date-Time Tool (current date/time, day computations)
"""

import ast
import operator
import math
from datetime import datetime, timedelta
from typing import Optional

from langchain_core.tools import tool


# ── Task 9: Calculator Tool ──────────────────────────────────────────────────

# Allowed operators for safe math evaluation
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
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
        expr = expr.replace("x", "*") if expr.count("x") == 1 and "x" not in ("max", "hex") else expr
        
        # Parse and safely evaluate
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval_node(tree)
        
        # Format nicely
        if isinstance(result, float) and result == int(result):
            return f"{expression} = {int(result)}"
        elif isinstance(result, float):
            return f"{expression} = {result:.6g}"
        return f"{expression} = {result}"
    except ZeroDivisionError:
        return "Error: Division by zero."
    except Exception as e:
        return f"Error evaluating '{expression}': {str(e)}"


from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os

# ── Task 10: Date-Time Tool ──────────────────────────────────────────────────

@tool
def datetime_tool(query: str) -> str:
    """Get current date, time, day of week, or compute days between dates.
    
    Handles queries like:
    - "current date", "today", "what day is it"
    - "current time", "what time is it"
    - "day of week"
    - "days until 2025-12-31"
    - "how far is 19 june from today"
    """
    now = datetime.now()
    current_time_str = now.strftime('%A, %B %d, %Y at %I:%M:%S %p')
    
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-3.5-flash",
            google_api_key=os.environ.get("GOOGLE_API_KEY"),
            temperature=0.0
        )
        prompt = PromptTemplate.from_template(
            "You are a precise calendar and time assistant. "
            "The current date and time is: {current_time}. "
            "Calculate or answer the user's date/time question accurately. "
            "If they ask for a future or past date without a year, assume the next/previous occurrence relative to the current date. "
            "Respond concisely with the answer.\n\n"
            "Question: {question}\n"
            "Answer:"
        )
        chain = prompt | llm | StrOutputParser()
        return chain.invoke({
            "current_time": current_time_str,
            "question": query
        }).strip()
    except Exception as e:
        # Fallback if LLM call fails
        return f"Current date and time: {current_time_str}. (Error calculating difference: {str(e)})"


# ── Tool Registry ────────────────────────────────────────────────────────────

ALL_TOOLS = [calculator, datetime_tool]
