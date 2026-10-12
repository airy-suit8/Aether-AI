"""Date-time tool (Task 10): every answer is computed in Python; no model is asked (R11)."""

from datetime import datetime

import pytest

from src.agents import tools


@pytest.fixture(autouse=True)
def monday_morning(monkeypatch):
    """Monday 12 October 2026, 09:05."""
    monkeypatch.setattr(tools, "_now", lambda: datetime(2026, 10, 12, 9, 5))


def ask(**args):
    return tools.datetime_tool.invoke(args)


def test_now_gives_the_date_weekday_and_time_without_asking_a_model(fake_llm):
    assert ask() == "Today is Monday, 12 October 2026. The time is 09:05."
    assert ask(operation="now") == ask()
    assert fake_llm.prompts == []


def test_the_real_clock_is_used_outside_tests(monkeypatch):
    monkeypatch.undo()
    assert f"{datetime.now():%B %Y}" in ask()


@pytest.mark.parametrize("args,answer", [
    ({"operation": "weekday", "start": "2026-12-25"}, "2026-12-25 is a Friday."),
    ({"operation": "weekday"}, "2026-10-12 is a Monday."),
    ({"operation": "days_between", "end": "2026-12-31"}, "From 2026-10-12 to 2026-12-31 is 80 days."),
    ({"operation": "days_between", "start": "2024-02-01", "end": "2024-03-01"}, "From 2024-02-01 to 2024-03-01 is 29 days."),  # a leap year
    ({"operation": "days_between", "start": "today", "end": "2026-10-12"}, "From 2026-10-12 to 2026-10-12 is 0 days."),
    ({"operation": "days_between", "start": "2026-10-12", "end": "2026-10-02"}, "2026-10-02 is 10 days before 2026-10-12."),
    ({"operation": "add_days", "days": 90}, "90 days after 2026-10-12 is Sunday, 10 January 2027 (2027-01-10)."),
    ({"operation": "add_days", "start": "2026-03-01", "days": -1}, "1 day before 2026-03-01 is Saturday, 28 February 2026 (2026-02-28)."),
    ({"operation": "days_between", "start": "2026-10-12", "end": "2026-10-13"}, "From 2026-10-12 to 2026-10-13 is 1 day."),
])
def test_date_arithmetic_is_exact(fake_llm, args, answer):
    assert ask(**args) == answer
    assert fake_llm.prompts == []


@pytest.mark.parametrize("args,message", [
    ({"operation": "weekday", "start": "31 December"}, "Error: '31 december' is not a date. Write dates as YYYY-MM-DD"),
    ({"operation": "days_between", "end": "2026-02-30"}, "Error: '2026-02-30' is not a date."),
    ({"operation": "add_days", "days": 10**9}, "Error:"),
    ({"operation": "guess"}, "Error: unknown operation 'guess'. Use one of: now, weekday, days_between, add_days."),
])
def test_bad_input_is_an_error_message_not_a_guess(args, message):
    assert ask(**args).startswith(message)


def test_registry_lists_both_tools():
    assert tools.ALL_TOOLS == [tools.calculator, tools.datetime_tool]
