# ------
# This file contains the agent workflow graph created using LangGraph
# ------

from langgraph.graph import StateGraph, START
from src.agents.state import OrderState
from src.agents.nodes.chatbot import chatbot
from src.agents.nodes.tool_node import tool_node
from langgraph.prebuilt import tools_condition
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def chatbot_agent_builder():
    NODE_CHATBOT = "chatbot"
    NODE_TOOLS = "tools"

    graph = StateGraph(OrderState)

    graph.add_node(NODE_CHATBOT, chatbot)
    graph.add_node(NODE_TOOLS, tool_node)

    graph.add_edge(START, NODE_CHATBOT)

    # Tool execution returns to chatbot so the model can continue
    # reasoning when another model turn is actually required.
    graph.add_edge(NODE_TOOLS, NODE_CHATBOT)
    graph.add_conditional_edges(NODE_CHATBOT, tools_condition)

    serializer = JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("src.agents.state", "ItemVariation"),
            ("src.agents.state", "CartItemUnit"),
            ("src.agents.state", "CartItem"),
            ("src.agents.state", "Cart"),
        ],
    )

    memory = MemorySaver(serde=serializer)
    chatbot_graph = graph.compile(checkpointer=memory)

    return chatbot_graph