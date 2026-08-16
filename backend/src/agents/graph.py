# ------
# This file contains the agent workflow graph created using LangGraph
# ------

from langgraph.graph import StateGraph, START
from src.agents.state import OrderState
from src.agents.nodes.chatbot import chatbot
from agents.nodes.tool_node import tool_node
from langgraph.prebuilt import tools_condition
from langgraph.checkpoint.memory import MemorySaver


def chatbot_agent_builder():
    NODE_CHATBOT = "chatbot"
    NODE_TOOLS = "tools"

    graph = StateGraph(OrderState)

    graph.add_node(NODE_CHATBOT, chatbot)
    graph.add_node(NODE_TOOLS, tool_node)

    graph.add_edge(START, NODE_CHATBOT)

    # tools will always return back to chatbot
    graph.add_edge(NODE_TOOLS, NODE_CHATBOT)
    graph.add_conditional_edges(NODE_CHATBOT, tools_condition)

    memory = MemorySaver()
    chatbot_graph = graph.compile(checkpointer=memory)

    return chatbot_graph
