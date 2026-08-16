# ----
# This file contains the State of the agent
# ----

from typing import Optional, TypedDict
from pydantic import BaseModel, Field
from typing import List, Annotated
from langgraph.graph.message import add_messages


# Cart Items & Cart


class ItemVariation(BaseModel):
    id: str = Field(description="Unique id of this variation for the item")
    name: str = Field(description="Name of this variation")
    price: str = Field(description="Price of this variation of the item")


class CartItemUnit(BaseModel):
    key: str = Field(
        description="Unique key for the item in the cart to match an item being added")
    quantity: int = Field(
        description="Quantity of this specific variation/customization")
    base_price: float = Field(
        description="Base price of the item (cannot be null)")
    variation: Optional[ItemVariation] = Field(
        default=None, description="Variation of the item if available")


class CartItem(BaseModel):
    item_id: str = Field(description="unique UUID for this item")
    title: str = Field(description="Name of the item")
    units: List[CartItemUnit]


class Cart(BaseModel):
    items: List[CartItem] = Field(default_factory=List)


class OrderState(TypedDict):
    """State representing the customer's order conversation."""

    # The `add_messages` annotation indicates to LangGraph
    # that state is updated by appending returned messages, not replacing
    # them.
    messages: Annotated[list, add_messages]

    # The customer's in-progress order.
    # its a list but can be a list of dict in real world to capture more details about the order
    # its essentialy the cart
    cart: Optional[Cart]

    orderId: Optional[str]

    # tenant specific
    restaurant_name: str
    subdomain: str

    # Flag indicating that the order is placed and completed.
    finished: bool
