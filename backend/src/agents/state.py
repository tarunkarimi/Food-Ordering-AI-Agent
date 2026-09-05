from typing import Annotated, List, Optional
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class ItemVariation(BaseModel):
    id: str
    name: str
    price: str


class CartItemUnit(BaseModel):
    key: str
    quantity: int
    base_price: float
    variation: Optional[ItemVariation] = None


class CartItem(BaseModel):
    item_id: str
    title: str
    units: List[CartItemUnit]


class Cart(BaseModel):
    items: List[CartItem] = Field(default_factory=list)


class OrderState(TypedDict):
    messages: Annotated[list, add_messages]
    cart: Optional[Cart]
    orderId: Optional[str]
    order_status: Optional[str]
    order_confirmation_pending: bool
    restaurant_name: str
    subdomain: str
    finished: bool