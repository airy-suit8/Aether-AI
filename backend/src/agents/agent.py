"""
agents/agent.py — Task 11.5: Multi-Step Agent Execution Layer
Uses LangChain's create_agent (a LangGraph agent loop) to allow the LLM to chain multiple tools together
(e.g., Search RAG -> Calculate Math -> Web Search -> Final Answer) while preserving
structured metadata for the UI.
"""

from typing import Callable

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError

from src.core.config import settings
from src.llm import llm_client
from src.memory.conversation import memory as _memory
from src.agents.tools import calculator, datetime_tool
from src.prompts.prompt_templates import AGENT_SYSTEM_PROMPT

# The answer when the agent hits settings.agent_recursion_limit
OUT_OF_STEPS = "Sorry, need more steps to process this request."




def run_agent(user_id: int, question: str, session_id: str,
              search_documents: Callable[[str], dict]) -> dict:
    """
    Agent Decision Layer — uses an Execution Loop (ReAct / Tool Calling).
    
    We define closure-based wrappers for our tools so we can dynamically track
    which tools the agent uses and intercept structured metadata from the RAG 
    engine (like sources and confidence) without losing them in the LLM loop.

    search_documents(query) answers a sub-question from the user's documents and returns
    {"answer", "sources", "confidence"}; the pipeline passes it in, and must not save the
    sub-question as a turn.

    Returns {"answer", "sources", "confidence", "tool_used"}. The turn is not saved here: the
    pipeline saves it once the answer has been sent, so a stream the client closed saves none.
    """
    
    metadata_store = {
        "sources": [],
        "confidence": None,  # set by a document search; an answer with no search has none (R11)
        "tool_used": set()
    }
    
    # ── Closure-based Tool Tracking Wrappers ──────────────────────────────────
    
    @tool
    def document_search_wrapper(query: str) -> str:
        """Search the user's uploaded documents for factual questions, general knowledge, summarizing content, or anything related to user documents."""
        metadata_store["tool_used"].add("document_search")
        rag_result = search_documents(query)
        
        # Merge sources and track minimum confidence across all searches
        metadata_store["sources"].extend(rag_result["sources"])
        earlier = metadata_store["confidence"]
        metadata_store["confidence"] = rag_result["confidence"] if earlier is None else min(earlier, rag_result["confidence"])

        return f"Document Search Result:\n{rag_result['answer']}"

    @tool
    def calculator_wrapper(expression: str) -> str:
        """Evaluate a mathematical expression safely."""
        metadata_store["tool_used"].add("calculator")
        return calculator.invoke(expression)

    @tool
    def datetime_wrapper(operation: str = "now", start: str = "", end: str = "", days: int = 0) -> str:
        """Date and time facts, computed exactly. Dates are written YYYY-MM-DD; an empty date means today.

        operation:
          "now"           the current date, weekday and time
          "weekday"       the weekday of `start`
          "days_between"  the number of days from `start` to `end`
          "add_days"      the date `days` days after `start` (a negative number goes back)
        """
        metadata_store["tool_used"].add("datetime")
        return datetime_tool.invoke({"operation": operation, "start": start, "end": end, "days": days})
        
    # ── Agent Orchestration ───────────────────────────────────────────────────
        
    tools = [
        calculator_wrapper, 
        datetime_wrapper, 
        document_search_wrapper
    ]
    
    llm = llm_client.get_llm(temperature=settings.tool_temperature)

    agent = create_agent(llm, tools, system_prompt=AGENT_SYSTEM_PROMPT)
    
    # Inject conversation history so the agent understands context (e.g. "assume 1890 km")
    history = _memory.get_history(user_id, session_id)
    messages = []
    for turn in history:
        messages.append(HumanMessage(content=turn["question"]))
        messages.append(AIMessage(content=turn["answer"]))
    messages.append(HumanMessage(content=question))
    
    # Run the multi-step execution loop. LangGraph's default limit is 10,000 steps, so a model
    # that keeps calling tools would run, and bill, almost without limit; the setting caps it.
    # Other errors propagate to the API, which reports them as errors instead of saving and
    # showing them as an answer.
    try:
        result = agent.invoke({"messages": messages}, config={"recursion_limit": settings.agent_recursion_limit})
    except GraphRecursionError:
        # create_agent raises at the limit; the old create_react_agent answered with this text
        result = {"messages": [AIMessage(content=OUT_OF_STEPS)]}

    # Extract the final answer from the LLM (.text joins content blocks into one string)
    final_answer = result["messages"][-1].text

    # Fallback: Sometimes Gemini fails to synthesize a final string after a tool call.
    # If the final text is empty, check if the previous message was a ToolMessage and use its raw output.
    if not final_answer.strip() and len(result["messages"]) > 1:
        prev_msg = result["messages"][-2]
        if getattr(prev_msg, "type", "") == "tool":
            final_answer = f"The result is: {prev_msg.text}"
        else:
            final_answer = "I executed the tool but encountered an issue formatting the final answer."
        
    # Deduplicate sources if the agent called document_search multiple times
    unique_sources = []
    seen = set()
    for s in metadata_store["sources"]:
        key = f"{s['source']}::{s['page']}"
        if key not in seen:
            seen.add(key)
            unique_sources.append(s)
            
    # Format tools used for the UI badge
    tools_used_str = " + ".join(sorted(list(metadata_store["tool_used"]))) if metadata_store["tool_used"] else "agent_direct"
    
    # Confidence is how close the retrieved passages were; an answer that searched no document
    # has none (it used to claim 1.0).
    return {
        "answer": final_answer,
        "sources": unique_sources,
        "confidence": metadata_store["confidence"],
        "tool_used": tools_used_str,
    }
