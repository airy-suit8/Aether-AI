"""
agent.py — Task 11.5: Multi-Step Agent Execution Layer
Uses LangGraph's create_react_agent to allow the LLM to chain multiple tools together
(e.g., Search RAG -> Calculate Math -> Web Search -> Final Answer) while preserving
structured metadata for the UI.
"""

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from tools import calculator, datetime_tool
from rag_engine import query_rag

from src.core.config import settings


# Maximum LangGraph steps per question (each tool call takes two). LangGraph's default is
# 10,000, so a model that keeps calling tools would run, and bill, almost without limit.
AGENT_RECURSION_LIMIT = settings.agent_recursion_limit


def _get_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.google_api_key,
        temperature=settings.tool_temperature,
    )


def run_agent(user_id: int, question: str, session_id: str = "default") -> dict:
    """
    Agent Decision Layer — uses an Execution Loop (ReAct / Tool Calling).
    
    We define closure-based wrappers for our tools so we can dynamically track
    which tools the agent uses and intercept structured metadata from the RAG 
    engine (like sources and confidence) without losing them in the LLM loop.
    """
    
    metadata_store = {
        "sources": [], 
        "confidence": 1.0, 
        "tool_used": set()
    }
    
    # ── Closure-based Tool Tracking Wrappers ──────────────────────────────────
    
    @tool
    def document_search_wrapper(query: str) -> str:
        """Search the user's uploaded documents for factual questions, general knowledge, summarizing content, or anything related to user documents."""
        metadata_store["tool_used"].add("document_search")
        # save_turn=False: this is the agent's internal sub-query; run_agent saves the user's turn
        rag_result = query_rag(user_id, query, session_id=session_id, save_turn=False)
        
        # Merge sources and track minimum confidence across all searches
        metadata_store["sources"].extend(rag_result["sources"])
        metadata_store["confidence"] = min(metadata_store["confidence"], rag_result["confidence"])
        
        return f"Document Search Result:\n{rag_result['answer']}"
        
    @tool
    def calculator_wrapper(expression: str) -> str:
        """Evaluate a mathematical expression safely."""
        metadata_store["tool_used"].add("calculator")
        return calculator.invoke(expression)
        
    @tool
    def datetime_wrapper(query: str) -> str:
        """Get current date, time, day of week, or compute days between dates."""
        metadata_store["tool_used"].add("datetime")
        return datetime_tool.invoke(query)
        
    # ── Agent Orchestration ───────────────────────────────────────────────────
        
    tools = [
        calculator_wrapper, 
        datetime_wrapper, 
        document_search_wrapper
    ]
    
    llm = _get_llm()
    
    system_prompt = (
        "You are the Aether AI Knowledge Assistant. You can chain multiple tools together to answer complex user questions.\n"
        "- If you need information from uploaded documents, use document_search_wrapper.\n"
        "- If you need to do math, use calculator_wrapper.\n"
        "- If you need date/time info, use datetime_wrapper.\n"
        "- If you need real-world facts, flight distances, prices, or general knowledge that is NOT in the user's documents, DO NOT attempt to search the web. Instead, rely on your own vast internal knowledge base to provide the data.\n"
        "Think step-by-step. Use the tools to gather necessary data, then synthesize the outputs into a clear final conversational answer.\n"
        "CRITICAL: After using a tool, you MUST output a final text response. NEVER return an empty string."
    )
    
    from langchain_core.messages import HumanMessage, AIMessage
    from rag_engine import _memory
    
    agent = create_react_agent(llm, tools, prompt=system_prompt)
    
    # Inject conversation history so the agent understands context (e.g. "assume 1890 km")
    history = _memory.get_history(user_id, session_id)
    messages = []
    for turn in history:
        messages.append(HumanMessage(content=turn["question"]))
        messages.append(AIMessage(content=turn["answer"]))
    messages.append(HumanMessage(content=question))
    
    # Run the multi-step execution loop. Errors propagate to the API, which reports
    # them as errors instead of saving and showing them as an answer.
    result = agent.invoke({"messages": messages}, config={"recursion_limit": AGENT_RECURSION_LIMIT})
    
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
    
    # Save the turn to memory so future agent calls or RAG calls remember this interaction
    confidence = metadata_store["confidence"] if metadata_store["tool_used"] else 1.0
    _memory.add_turn(user_id, session_id, question, final_answer, confidence, mode="agent")
    
    return {
        "answer": final_answer,
        "sources": unique_sources,
        "confidence": metadata_store["confidence"] if metadata_store["tool_used"] else 1.0,
        "tool_used": tools_used_str
    }
