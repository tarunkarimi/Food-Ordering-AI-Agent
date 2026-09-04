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

// Use Vite's local proxy to avoid browser CORS problems.
const MENU_API = "/menu-api";
const AI_API = "";

function extractAssistantText(rawResponse) {
  if (!rawResponse) return "";

  const raw = String(rawResponse).trim();

  // Backend returns SSE:
  // data: {"type":"AIMessage","content":"[{'type':'text','text':'...'}]"}
  // data: [DONE]

  const lines = raw.split(/\r?\n/);

  for (const line of lines) {
    if (!line.startsWith("data:")) continue;

    const payload = line.replace(/^data:\s*/, "").trim();

    if (!payload || payload === "[DONE]") continue;

    // Parse the outer JSON object.
    try {
      const outer = JSON.parse(payload);

      if (typeof outer.content === "string") {
        const content = outer.content;

        // Extract the inner text value from:
        // [{'type': 'text', 'text': "...", 'extras': {...}}]
        const match = content.match(
          /['"]text['"]\s*:\s*(["'])([\s\S]*?)\1\s*,\s*['"]extras['"]\s*:/
        );

        if (match && match[2]) {
          return decodeEscapedText(match[2]).trim();
        }

        // Fallback for a content string that is already plain text.
        if (
          !content.startsWith("[") &&
          !content.startsWith("{")
        ) {
          return content.trim();
        }
      }

      // Other normal response formats.
      if (typeof outer.text === "string") {
        return outer.text.trim();
      }

      if (typeof outer.message === "string") {
        return outer.message.trim();
      }
    } catch {
      // Continue to the next SSE line.
    }
  }

  // Fallback: try the whole response as JSON.
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

function readQuotedValue(source, start, quote) {
  let escaped = false;
  let result = "";

  for (let i = start; i < source.length; i += 1) {
    const char = source[i];

    if (escaped) {
      result += char;
      escaped = false;
      continue;
    }

    if (char === "\\") {
      result += char;
      escaped = true;
      continue;
    }

    // Python repr commonly contains apostrophes inside a double-quoted
    // string or escaped apostrophes inside a single-quoted string.
    if (char === quote) {
      const rest = source.slice(i + 1);
      if (
        /^\s*(?:,|\})/.test(rest) ||
        /^\s*$/.test(rest)
      ) {
        return result;
      }
    }

    result += char;
  }

  return result;
}

function extractTextFromValue(value) {
  if (value === null || value === undefined) return "";

  // Direct string
  if (typeof value === "string") {
    const text = value.trim();
    if (!text) return "";

    // The AI backend can return content like:
    // "[{'type': 'text', 'text': 'Namaste! Welcome to Test Restaurant...'}]"
    //
    // Extract the nested "text" value instead of displaying the
    // complete Python-style representation.
    const textKeyMatch = text.match(/['"]text['"]\s*:\s*(['"])/);

    if (textKeyMatch) {
      const quote = textKeyMatch[1];
      const valueStart =
        textKeyMatch.index + textKeyMatch[0].length;

      const extracted = readQuotedValue(text, valueStart, quote);

      if (extracted) {
        return decodeEscapedText(extracted).trim();
      }
    }

    return text;
  }

  // Array of message/content objects
  if (Array.isArray(value)) {
    for (const item of value) {
      const extracted = extractTextFromValue(item);
      if (extracted) return extracted;
    }
    return "";
  }

  // Object response
  if (typeof value === "object") {
    // Example:
    // { type: "text", text: "Namaste!" }
    if (
      value.type === "text" &&
      typeof value.text === "string" &&
      value.text.trim()
    ) {
      return value.text.trim();
    }

    // AIMessage:
    // {
    //   type: "AIMessage",
    //   content: "[{'type': 'text', 'text': '...'}]"
    // }
    if (typeof value.content === "string" && value.content.trim()) {
      const extracted = extractTextFromValue(value.content);
      if (extracted) return extracted;
    }

    if (Array.isArray(value.content)) {
      const extracted = extractTextFromValue(value.content);
      if (extracted) return extracted;
    }

    // Other possible response formats
    for (const key of ["text", "message", "response", "answer"]) {
      if (typeof value[key] === "string" && value[key].trim()) {
        return value[key].trim();
      }
    }
  }

  return "";
}

function decodeEscapedText(text) {
  if (!text) return "";

  try {
    return JSON.parse(`"${text.replace(/"/g, '\\"')}"`);
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
  const [restaurant, setRestaurant] = useState("Test Restaurant");
  const [loadingMenu, setLoadingMenu] = useState(true);
  const [menuError, setMenuError] = useState("");

  const [cart, setCart] = useState([]);

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Namaste! 🙏 I'm your AI food assistant. Ask me about the menu or tell me what you'd like to order.",
    },
  ]);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  const [order, setOrder] = useState(null);
  const [placingOrder, setPlacingOrder] = useState(false);

  const cartItemCount = useMemo(
    () => cart.reduce((total, item) => total + Number(item.quantity || 0), 0),
    [cart]
  );

  const subtotal = useMemo(
    () =>
      cart.reduce(
        (total, item) =>
          total +
          Number(item.base_price || 0) * Number(item.quantity || 0),
        0
      ),
    [cart]
  );

  useEffect(() => {
    loadMenu();
  }, []);

  async function loadMenu() {
    try {
      setLoadingMenu(true);
      setMenuError("");

      const response = await fetch(`${MENU_API}/?subdomain=test`);

      if (!response.ok) {
        throw new Error(`Menu service returned ${response.status}`);
      }

      const data = await response.json();

      const items = Array.isArray(data?.items)
        ? data.items
        : Array.isArray(data)
        ? data
        : [];

      setMenu(items);

      if (data?.restaurant_name) {
        setRestaurant(data.restaurant_name);
      }

      if (!items.length) {
        setMenuError("The restaurant returned an empty menu.");
      }
    } catch (error) {
      console.error("Menu loading error:", error);
      setMenuError(
        "Could not load the restaurant menu. Check that the menu backend is running on port 8000."
      );
    } finally {
      setLoadingMenu(false);
    }
  }

  function addToCart(item) {
    setCart((previous) => {
      const existing = previous.find((cartItem) => cartItem.id === item.id);

      if (existing) {
        return previous.map((cartItem) =>
          cartItem.id === item.id
            ? { ...cartItem, quantity: cartItem.quantity + 1 }
            : cartItem
        );
      }

      return [...previous, { ...item, quantity: 1 }];
    });
  }

  function decreaseQuantity(itemId) {
    setCart((previous) =>
      previous
        .map((item) =>
          item.id === itemId
            ? { ...item, quantity: item.quantity - 1 }
            : item
        )
        .filter((item) => item.quantity > 0)
    );
  }

  function removeFromCart(itemId) {
    setCart((previous) => previous.filter((item) => item.id !== itemId));
  }

  async function sendMessage(event) {
    event.preventDefault();

    const message = input.trim();
    if (!message || sending) return;

    setInput("");
    setMessages((previous) => [
      ...previous,
      { role: "user", content: message },
    ]);

    try {
      setSending(true);

      const sessionId =
        localStorage.getItem("food_agent_session") || crypto.randomUUID();

      localStorage.setItem("food_agent_session", sessionId);

      const response = await fetch(`${AI_API}/api/chats/orders`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_message: message,
          session_id: sessionId,
          restaurant_name: restaurant,
          subdomain: "test",
        }),
      });

      const rawResponse = await response.text();
      console.log("AI raw response:", rawResponse);

      if (!response.ok) {
        throw new Error(`AI request failed: ${response.status}`);
      }

      const assistantText = extractAssistantText(rawResponse);

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
      console.error("AI request error:", error);

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
    if (cart.length === 0 || placingOrder) return;

    try {
      setPlacingOrder(true);

      const response = await fetch(`${MENU_API}/orders`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          restaurant_name: restaurant,
          subdomain: "test",
          items: cart.map((item) => ({
            item_id: item.id,
            title: item.title,
            quantity: item.quantity,
            base_price: item.base_price,
            variation: null,
          })),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Order failed");
      }

      setOrder(data);
      setCart([]);

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: `Your order ${data.order_id} has been confirmed! 🎉 Your subtotal is ₹${Number(
            data.subtotal || 0
          ).toFixed(2)}.`,
        },
      ]);
    } catch (error) {
      console.error("Order error:", error);

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
      const response = await fetch(`${MENU_API}/orders/${order.order_id}`, {
        method: "DELETE",
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Cancellation failed");
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
      console.error("Cancellation error:", error);

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
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-icon">
            <Utensils size={22} />
          </div>

          <div>
            <h1>FoodAI</h1>
            <span>AI-powered food ordering</span>
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
              <p className="eyebrow">TODAY'S MENU</p>
              <h2>What are you craving?</h2>
            </div>

            <div className="menu-count">{menu.length} items</div>
          </div>

          {loadingMenu ? (
            <div className="loading">
              <Loader2 className="spin" />
              Loading menu...
            </div>
          ) : menuError ? (
            <div className="loading">
              <p>{menuError}</p>
              <button className="add-button" onClick={loadMenu}>
                Try Again
              </button>
            </div>
          ) : (
            <div className="menu-grid">
              {menu.map((item) => (
                <article className="food-card" key={item.id}>
                  <div className="food-image">🍛</div>

                  <div className="food-info">
                    <h3>{item.title}</h3>

                    <p>
                      {item.description ||
                        "Delicious food prepared fresh for you."}
                    </p>

                    <div className="food-bottom">
                      <strong>₹{Number(item.base_price || 0).toFixed(2)}</strong>

                      <button
                        className="add-button"
                        onClick={() => addToCart(item)}
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
                <h3>FoodAI Assistant</h3>
                <span>Online • Ready to order</span>
              </div>
            </div>

            <div className="messages">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={`message ${
                    message.role === "user" ? "user-message" : "ai-message"
                  }`}
                >
                  {message.content}
                </div>
              ))}

              {sending && (
                <div className="message ai-message typing">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              )}
            </div>

            <form className="chat-input" onSubmit={sendMessage}>
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask me what you'd like..."
                disabled={sending}
              />

              <button
                type="submit"
                disabled={!input.trim() || sending}
                aria-label="Send message"
              >
                {sending ? (
                  <Loader2 className="spin" size={18} />
                ) : (
                  <Send size={18} />
                )}
              </button>
            </form>
          </section>

          <section className="cart-card">
            <div className="card-title">
              <div>
                <p className="eyebrow">YOUR ORDER</p>

                <h3>
                  <ShoppingCart size={19} />
                  Cart
                </h3>
              </div>

              <span>{cartItemCount} items</span>
            </div>

            {cart.length === 0 ? (
              <div className="empty-cart">
                <ShoppingCart size={35} />

                <p>Your cart is empty</p>

                <span>Add something delicious from the menu.</span>
              </div>
            ) : (
              <>
                <div className="cart-items">
                  {cart.map((item) => (
                    <div className="cart-item" key={item.id}>
                      <div className="cart-item-info">
                        <strong>{item.title}</strong>

                        <span>
                          ₹{Number(item.base_price || 0).toFixed(2)} ×{" "}
                          {item.quantity}
                        </span>
                      </div>

                      <div className="quantity-controls">
                        <button
                          type="button"
                          onClick={() => decreaseQuantity(item.id)}
                        >
                          <Minus size={14} />
                        </button>

                        <span>{item.quantity}</span>

                        <button
                          type="button"
                          onClick={() => addToCart(item)}
                        >
                          <Plus size={14} />
                        </button>

                        <button
                          type="button"
                          className="delete-button"
                          onClick={() => removeFromCart(item.id)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="cart-total">
                  <span>Subtotal</span>
                  <strong>₹{subtotal.toFixed(2)}</strong>
                </div>

                <button
                  className="checkout-button"
                  onClick={placeOrder}
                  disabled={placingOrder}
                >
                  {placingOrder ? (
                    <>
                      <Loader2 className="spin" size={18} />
                      Placing order...
                    </>
                  ) : (
                    <>
                      <CheckCircle2 size={18} />
                      Place Order
                    </>
                  )}
                </button>
              </>
            )}
          </section>

          {order && (
            <section
              className={`order-status ${
                order.status === "cancelled" ? "cancelled" : ""
              }`}
            >
              <div className="order-status-header">
                {order.status === "cancelled" ? (
                  <XCircle size={22} />
                ) : (
                  <CheckCircle2 size={22} />
                )}

                <div>
                  <strong>{order.order_id}</strong>
                  <span>{order.status}</span>
                </div>
              </div>

              {order.status === "confirmed" && (
                <button className="cancel-order" onClick={cancelOrder}>
                  Cancel Order
                </button>
              )}
            </section>
          )}
        </aside>
      </main>
    </div>
  );
}

export default App;




