"""Date-time tool (Task 10): the model is given the current date; a failure falls back to it."""

from datetime import datetime

import tools


def test_the_model_is_given_the_current_date_and_the_question(fake_llm):
    answer = tools.datetime_tool.invoke("how many days until 31 December?")
    today = datetime.now().strftime("%A, %B %d, %Y")
    assert answer.startswith("Date answer.") and today in answer
    prompt = fake_llm.prompts[-1]
    assert today in prompt
    assert "Question: how many days until 31 December?" in prompt


def test_a_model_failure_still_returns_the_current_date(fake_llm):
    fake_llm.fail_with = "quota exceeded"
    answer = tools.datetime_tool.invoke("what day is it?")
    assert answer.startswith("Current date and time: " + datetime.now().strftime("%A, %B %d, %Y"))
    assert "quota exceeded" in answer


def test_registry_lists_both_tools():
    assert tools.ALL_TOOLS == [tools.calculator, tools.datetime_tool]
