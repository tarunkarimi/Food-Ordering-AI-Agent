import { useEffect, useMemo, useState } from "react";
import {
  Bot,
  ShoppingCart,
  Plus,
  Minus,
  Trash2,
  Send,
  Utensils,
  CheckCircle2,
  XCircle,
  Loader2,
} from "lucide-react";
import "./App.css";

const MENU_API = "/menu-api";
const AI_API = "";

function extractAssistantText(rawResponse) {
  if (!rawResponse) return "";

  const raw = String(rawResponse).trim();
  const lines = raw.split(/\r?\n/);

  for (const line of lines) {
    if (!line.startsWith("data:")) continue;

    const payload = line.replace(/^data:\s*/, "").trim();

    if (!payload || payload === "[DONE]") continue;

    try {
      const outer = JSON.parse(payload);

      if (typeof outer.content === "string") {
        const content = outer.content;

        const match = content.match(
          /['"]text['"]\s*:\s*(["'])([\s\S]*?)\1\s*,\s*['"]extras['"]\s*:/
        );

        if (match && match[2]) {
          return decodeEscapedText(match[2]).trim();
        }

        if (
          !content.startsWith("[") &&
          !content.startsWith("{")
        ) {
          return content.trim();
        }
      }

      if (typeof outer.text === "string") {
        return outer.text.trim();
      }

      if (typeof outer.message === "string") {
        return outer.message.trim();
      }
    } catch {
      // Continue.
    }
  }

  try {
    const parsed = JSON.parse(raw);

    if (typeof parsed === "string") {
      return parsed.trim();
    }

    if (typeof parsed?.content === "string") {
      return parsed.content.trim();
    }

    if (typeof parsed?.text === "string") {
      return parsed.text.trim();
    }
  } catch {
    // Ignore.
  }

  return "";
}

function decodeEscapedText(text) {
  if (!text) return "";

  try {
    return JSON.parse(
      `"${text.replace(/"/g, '\\"')}"`
    );
  } catch {
    return text
      .replace(/\\n/g, "\n")
      .replace(/\\"/g, '"')
      .replace(/\\'/g, "'")
      .replace(/\\\\/g, "\\");
  }
}

function App() {
  const [menu, setMenu] = useState([]);
  const [restaurant, setRestaurant] =
    useState("Test Restaurant");
  const [loadingMenu, setLoadingMenu] =
    useState(true);
  const [menuError, setMenuError] = useState("");

  const [cart, setCart] = useState([]);
  const [variationModalItem, setVariationModalItem] = useState(null);
  const [variationModalSelection, setVariationModalSelection] = useState(null);

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Namaste! ðŸ™ I'm your AI food assistant. Ask me about the menu or tell me what you'd like to order.",
    },
  ]);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [cartUpdating, setCartUpdating] =
    useState(false);

  const [order, setOrder] = useState(null);
  const [placingOrder, setPlacingOrder] =
    useState(false);

  const [sessionId] = useState(() => {
    const existingSession =
      localStorage.getItem(
        "food_agent_session"
      );

    if (existingSession) {
      return existingSession;
    }

    const newSession = crypto.randomUUID();

    localStorage.setItem(
      "food_agent_session",
      newSession
    );

    return newSession;
  });

  const cartItemCount = useMemo(
    () =>
      cart.reduce(
        (total, item) =>
          total + Number(item.quantity || 0),
        0
      ),
    [cart]
  );

  const subtotal = useMemo(
    () =>
      cart.reduce(
        (total, item) =>
          total +
          Number(item.base_price || 0) *
            Number(item.quantity || 0),
        0
      ),
    [cart]
  );

  useEffect(() => {
    loadMenu();
    syncCartFromAI(sessionId);
  }, [sessionId]);

  async function loadMenu() {
    try {
      setLoadingMenu(true);
      setMenuError("");

      const response = await fetch(
        `${MENU_API}/?subdomain=test`
      );

      if (!response.ok) {
        throw new Error(
          `Menu service returned ${response.status}`
        );
      }

      const data = await response.json();

      const items = Array.isArray(data?.items)
        ? data.items
        : Array.isArray(data)
        ? data
        : [];

      setMenu(items);

      if (data?.restaurant_name) {
        setRestaurant(
          data.restaurant_name
        );
      }

      if (!items.length) {
        setMenuError(
          "The restaurant returned an empty menu."
        );
      }
    } catch (error) {
      console.error(
        "Menu loading error:",
        error
      );

      setMenuError(
        "Could not load the restaurant menu. Check that the menu backend is running on port 8000."
      );
    } finally {
      setLoadingMenu(false);
    }
  }

  async function syncCartFromAI(currentSessionId) {
    try {
      const response = await fetch(
        `/api/chats/state?session_id=${encodeURIComponent(
          currentSessionId
        )}`
      );

      if (!response.ok) {
        throw new Error(
          `State request failed: ${response.status}`
        );
      }

      const data = await response.json();

      const backendCart = data?.[0]?.cart;

      if (
        !backendCart ||
        !Array.isArray(backendCart.items)
      ) {
        setCart([]);
        return;
      }

      const syncedCart =
        backendCart.items.flatMap(
          (item) =>
            (item.units || []).map(
              (unit) => ({
                id:
                  unit.key ||
                  item.item_id,
                item_id: item.item_id,
                title: item.title,
                quantity: Number(
                  unit.quantity || 0
                ),
                base_price: Number(
                  unit.base_price || 0
                ),
                variation:
                  unit.variation || null,
              })
            )
        );

      setCart(
        syncedCart.filter(
          (item) =>
            item.quantity > 0
        )
      );
    } catch (error) {
      console.error(
        "Cart sync error:",
        error
      );
    }
  }

  async function manualCartRequest(
    endpoint,
    item,
    quantity = 1
  ) {
    try {
      setCartUpdating(true);

      const response = await fetch(
        `/api/chats/cart/${endpoint}`,
        {
          method: "POST",
          headers: {
            "Content-Type":
              "application/json",
          },
          body: JSON.stringify({
            session_id: sessionId,
            restaurant_name:
              restaurant,
            subdomain: "test",
            item_id:
              item?.item_id ||
              item?.id ||
              null,
            title:
              item?.title || null,
            quantity,
            variation_id:
              item?.variation?.id ||
              null,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data?.detail ||
            "Cart update failed"
        );
      }

      await syncCartFromAI(sessionId);
    } catch (error) {
      console.error(
        "Manual cart update error:",
        error
      );

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `I couldn't update your cart: ${error.message}`,
        },
      ]);
    } finally {
      setCartUpdating(false);
    }
  }

  function getItemVariations(item) {
    return Array.isArray(item?.variations)
      ? item.variations
      : [];
  }

  function getItemPrice(item) {
    if (item?.variation?.price !== undefined) {
      return Number(item.variation.price || 0);
    }

    return Number(item?.base_price || 0);
  }

  function openVariationModal(item) {
    const variations = getItemVariations(item);

    if (!variations.length) {
      addToCart(item);
      return;
    }

    setVariationModalItem(item);
    setVariationModalSelection(variations[0] || null);
  }

  function closeVariationModal() {
    if (cartUpdating) return;
    setVariationModalItem(null);
    setVariationModalSelection(null);
  }

  async function confirmVariationAdd() {
    if (!variationModalItem || !variationModalSelection) return;

    const item = variationModalItem;
    const variation = variationModalSelection;

    setVariationModalItem(null);
    setVariationModalSelection(null);

    await addToCart({ ...item, variation });
  }

  async function addToCart(item) {
    await manualCartRequest(
      "add",
      item,
      1
    );
  }

  async function decreaseQuantity(item) {
    await manualCartRequest(
      "remove",
      item,
      1
    );
  }

  async function removeFromCart(item) {
    await manualCartRequest(
      "remove",
      item,
      Number(item.quantity || 1)
    );
  }

  async function clearCart() {
    try {
      setCartUpdating(true);

      const response = await fetch(
        "/api/chats/cart/clear",
        {
          method: "POST",
          headers: {
            "Content-Type":
              "application/json",
          },
          body: JSON.stringify({
            session_id: sessionId,
            restaurant_name:
              restaurant,
            subdomain: "test",
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data?.detail ||
            "Unable to clear cart"
        );
      }

      await syncCartFromAI(sessionId);
    } catch (error) {
      console.error(
        "Clear cart error:",
        error
      );

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `I couldn't clear your cart: ${error.message}`,
        },
      ]);
    } finally {
      setCartUpdating(false);
    }
  }

  async function sendMessage(event) {
    event.preventDefault();

    const message = input.trim();

    if (!message || sending) return;

    setInput("");

    setMessages((previous) => [
      ...previous,
      {
        role: "user",
        content: message,
      },
    ]);

    try {
      setSending(true);

      const response = await fetch(
        `${AI_API}/api/chats/orders`,
        {
          method: "POST",
          headers: {
            "Content-Type":
              "application/json",
          },
          body: JSON.stringify({
            user_message: message,
            session_id: sessionId,
            restaurant_name:
              restaurant,
            subdomain: "test",
          }),
        }
      );

      const rawResponse =
        await response.text();

      console.log(
        "AI raw response:",
        rawResponse
      );

      if (!response.ok) {
        throw new Error(
          `AI request failed: ${response.status}`
        );
      }

      const assistantText =
        extractAssistantText(
          rawResponse
        );

      await syncCartFromAI(sessionId);

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content:
            assistantText ||
            "I received your request, but I couldn't format the AI response.",
        },
      ]);
    } catch (error) {
      console.error(
        "AI request error:",
        error
      );

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content:
            "Sorry, I couldn't connect to the AI ordering service. Please make sure the AI backend on port 8001 is running.",
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  async function placeOrder() {
    if (
      cart.length === 0 ||
      placingOrder
    ) {
      return;
    }

    try {
      setPlacingOrder(true);

      const response = await fetch(
        `${MENU_API}/orders`,
        {
          method: "POST",
          headers: {
            "Content-Type":
              "application/json",
          },
          body: JSON.stringify({
            restaurant_name:
              restaurant,
            subdomain: "test",
            items: cart.map(
              (item) => ({
                item_id:
                  item.item_id ||
                  item.id,
                title: item.title,
                quantity:
                  item.quantity,
                base_price:
                  item.base_price,
                variation:
                  item.variation ||
                  null,
              })
            ),
          }),
        }
      );

      const data =
        await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Order failed"
        );
      }

      setOrder(data);

      // Keep the LangGraph cart in sync
      // after a successful manual checkout.
      await clearCart();

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `Your order ${data.order_id} has been confirmed! ðŸŽ‰ Your subtotal is â‚¹${Number(
            data.subtotal || 0
          ).toFixed(2)}.`,
        },
      ]);
    } catch (error) {
      console.error(
        "Order error:",
        error
      );

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `I couldn't place the order: ${error.message}`,
        },
      ]);
    } finally {
      setPlacingOrder(false);
    }
  }

  async function cancelOrder() {
    if (!order) return;

    try {
      const response = await fetch(
        `${MENU_API}/orders/${order.order_id}`,
        {
          method: "DELETE",
        }
      );

      const data =
        await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Cancellation failed"
        );
      }

      setOrder(data);

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `Order ${data.order_id} has been cancelled.`,
        },
      ]);
    } catch (error) {
      console.error(
        "Cancellation error:",
        error
      );

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `I couldn't cancel the order: ${error.message}`,
        },
      ]);
    }
  }

  return (
    <>
      <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-icon">
            <Utensils size={22} />
          </div>

          <div>
            <h1>FoodAI</h1>
            <span>
              AI-powered food ordering
            </span>
          </div>
        </div>

        <div className="restaurant-status">
          <span className="status-dot"></span>
          {restaurant}
        </div>
      </header>

      <main className="layout">
        <section className="menu-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">
                TODAY'S MENU
              </p>

              <h2>
                What are you craving?
              </h2>
            </div>

            <div className="menu-count">
              {menu.length} items
            </div>
          </div>

          {loadingMenu ? (
            <div className="loading">
              <Loader2 className="spin" />
              Loading menu...
            </div>
          ) : menuError ? (
            <div className="loading">
              <p>{menuError}</p>

              <button
                className="add-button"
                onClick={loadMenu}
              >
                Try Again
              </button>
            </div>
          ) : (
            <div className="menu-grid">
              {menu.map((item) => (
                <article
                  className="food-card"
                  key={item.id}
                >
                  <div className="food-image">
                    ðŸ²
                  </div>

                  <div className="food-info">
                    <h3>{item.title}</h3>

                    <p>
                      {item.description ||
                        "Delicious food prepared fresh for you."}
                    </p>

                    <div className="food-bottom">
                      <strong>
                        {getItemVariations(item).length > 0
                          ? `From â‚¹${Number(
                              getItemVariations(item)[0]?.price ||
                                item.base_price ||
                                0
                            ).toFixed(2)}`
                          : `â‚¹${getItemPrice(item).toFixed(2)}`}
                      </strong>

                      <button
                        className="add-button"
                        onClick={() =>
                          openVariationModal(item)
                        }
                        disabled={
                          cartUpdating
                        }
                      >
                        <Plus size={17} />
                        Add
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <aside className="right-panel">
          <section className="chat-card">
            <div className="card-header">
              <div className="ai-avatar">
                <Bot size={21} />
              </div>

              <div>
                <h3>
                  FoodAI Assistant
                </h3>

                <span>
                  Online â€¢ Ready to order
                </span>
              </div>
            </div>

            <div className="messages">
              {messages.map(
                (message, index) => (
                  <div
                    key={index}
                    className={`message ${
                      message.role ===
                      "user"
                        ? "user-message"
                        : "ai-message"
                    }`}
                  >
                    {message.content}
                  </div>
                )
              )}

              {sending && (
                <div className="message ai-message typing">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              )}
            </div>

            <form
              className="chat-input"
              onSubmit={sendMessage}
            >
              <input
                value={input}
                onChange={(event) =>
                  setInput(
                    event.target.value
                  )
                }
                placeholder="Ask me what you'd like..."
                disabled={sending}
              />

              <button
                type="submit"
                disabled={
                  !input.trim() ||
                  sending
                }
                aria-label="Send message"
              >
                {sending ? (
                  <Loader2
                    className="spin"
                    size={18}
                  />
                ) : (
                  <Send size={18} />
                )}
              </button>
            </form>
          </section>

          <section className="cart-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">
                  YOUR ORDER
                </p>

                <h3>
                  <ShoppingCart
                    size={19}
                  />
                  Cart
                </h3>
              </div>

              <span>
                {cartItemCount} items
              </span>
            </div>

            {cart.length === 0 ? (
              <div className="empty-cart">
                <ShoppingCart size={35} />

                <p>
                  Your cart is empty
                </p>

                <span>
                  Add something delicious
                  from the menu.
                </span>
              </div>
            ) : (
              <>
                <div className="cart-items">
                  {cart.map((item) => (
                    <div
                      className="cart-item"
                      key={item.id}
                    >
                      <div className="cart-item-info">
                        <strong>
                          {item.title}
                        </strong>

                        {item.variation?.name && (
                          <span>
                            {item.variation.name}
                          </span>
                        )}

                        <span>
                          â‚¹{Number(
                            item.base_price ||
                              0
                          ).toFixed(2)}{" "}
                          Ã—{" "}
                          {item.quantity}
                        </span>
                      </div>

                      <div className="quantity-controls">
                        <button
                          type="button"
                          disabled={
                            cartUpdating
                          }
                          onClick={() =>
                            decreaseQuantity(
                              item
                            )
                          }
                        >
                          <Minus size={14} />
                        </button>

                        <span>
                          {item.quantity}
                        </span>

                        <button
                          type="button"
                          disabled={
                            cartUpdating
                          }
                          onClick={() =>
                            addToCart(item)
                          }
                        >
                          <Plus size={14} />
                        </button>

                        <button
                          type="button"
                          className="delete-button"
                          disabled={
                            cartUpdating
                          }
                          onClick={() =>
                            removeFromCart(
                              item
                            )
                          }
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="cart-total">
                  <span>
                    Subtotal
                  </span>

                  <strong>
                    â‚¹{subtotal.toFixed(2)}
                  </strong>
                </div>

                <button
                  className="checkout-button"
                  onClick={placeOrder}
                  disabled={
                    placingOrder ||
                    cartUpdating
                  }
                >
                  {placingOrder ? (
                    <>
                      <Loader2
                        className="spin"
                        size={18}
                      />
                      Placing order...
                    </>
                  ) : (
                    <>
                      <CheckCircle2
                        size={18}
                      />
                      Place Order
                    </>
                  )}
                </button>

                <button
                  type="button"
                  className="cancel-order"
                  onClick={clearCart}
                  disabled={
                    cartUpdating ||
                    placingOrder
                  }
                >
                  {cartUpdating ? (
                    <>
                      <Loader2
                        className="spin"
                        size={16}
                      />
                      Updating...
                    </>
                  ) : (
                    "Clear Cart"
                  )}
                </button>
              </>
            )}
          </section>

          {order && (
            <section
              className={`order-status ${
                order.status ===
                "cancelled"
                  ? "cancelled"
                  : ""
              }`}
            >
              <div className="order-status-header">
                {order.status ===
                "cancelled" ? (
                  <XCircle size={22} />
                ) : (
                  <CheckCircle2
                    size={22}
                  />
                )}

                <div>
                  <strong>
                    {order.order_id}
                  </strong>

                  <span>
                    {order.status}
                  </span>
                </div>
              </div>

              {order.status ===
                "confirmed" && (
                <button
                  className="cancel-order"
                  onClick={cancelOrder}
                >
                  Cancel Order
                </button>
              )}
            </section>
          )}
        </aside>
      </main>
      </div>

      {variationModalItem && (
        <div
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeVariationModal();
          }}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "20px",
            background: "rgba(0,0,0,0.72)",
            backdropFilter: "blur(5px)",
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="variation-modal-title"
            style={{
              width: "100%",
              maxWidth: "430px",
              maxHeight: "90vh",
              overflowY: "auto",
              background: "#151518",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: "20px",
              boxShadow: "0 24px 80px rgba(0,0,0,0.55)",
              padding: "24px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", marginBottom: "20px" }}>
              <div>
                <div style={{ fontSize: "12px", fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "#9b55ff", marginBottom: "7px" }}>
                  Choose an option
                </div>
                <h3 id="variation-modal-title" style={{ margin: 0, fontSize: "22px", color: "#fff" }}>
                  {variationModalItem.title}
                </h3>
                <p style={{ margin: "7px 0 0", color: "#92929b", fontSize: "13px" }}>
                  Select your preferred size or option
                </p>
              </div>
              <button type="button" onClick={closeVariationModal} disabled={cartUpdating} aria-label="Close" style={{ width: "34px", height: "34px", flexShrink: 0, border: "1px solid rgba(255,255,255,0.1)", borderRadius: "50%", background: "#202023", color: "#bdbdc6", fontSize: "22px", cursor: "pointer" }}>Ã—</button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {getItemVariations(variationModalItem).map((variation) => {
                const selected = variationModalSelection?.id === variation.id;
                return (
                  <button
                    key={variation.id}
                    type="button"
                    onClick={() => setVariationModalSelection(variation)}
                    disabled={cartUpdating}
                    style={{
                      width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px", padding: "15px 16px", borderRadius: "14px",
                      border: selected ? "1px solid #8b3dff" : "1px solid rgba(255,255,255,0.09)",
                      background: selected ? "rgba(139,61,255,0.14)" : "#1d1d20", color: "#fff", textAlign: "left", cursor: "pointer",
                    }}
                  >
                    <span style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                      <span style={{ width: "20px", height: "20px", borderRadius: "50%", border: selected ? "6px solid #8b3dff" : "2px solid #77777f", boxSizing: "border-box" }} />
                      <span style={{ fontSize: "15px", fontWeight: 600 }}>{variation.name}</span>
                    </span>
                    <span style={{ fontSize: "15px", fontWeight: 700, whiteSpace: "nowrap" }}>
                      â‚¹{Number(variation.price || 0).toFixed(2)}
                    </span>
                  </button>
                );
              })}
            </div>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px", marginTop: "22px", paddingTop: "18px", borderTop: "1px solid rgba(255,255,255,0.08)" }}>
              <div>
                <span style={{ display: "block", fontSize: "12px", color: "#8d8d97", marginBottom: "4px" }}>Selected</span>
                <strong style={{ fontSize: "17px", color: "#fff" }}>{variationModalSelection?.name || "Choose an option"}</strong>
              </div>
              <button type="button" className="add-button" onClick={confirmVariationAdd} disabled={cartUpdating || !variationModalSelection} style={{ minWidth: "145px", justifyContent: "center" }}>
                <Plus size={17} />
                Add to Cart
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default App;

