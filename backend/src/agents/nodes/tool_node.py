from agents.tools.cart import get_menu, get_cart, add_cart, remove_from_cart, place_order, confirm_order
from langgraph.prebuilt import ToolNode


tools = [get_menu, get_cart, add_cart,
         remove_from_cart, place_order, confirm_order]

# we use prebuilt ToolNode from LangGraph
# we use prebuilt ToolNode from LangGraph
tool_node = ToolNode(tools)
