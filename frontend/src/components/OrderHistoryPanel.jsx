import { useState } from "react";

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString();
}

export default function OrderHistoryPanel({ onReorder }) {
  const [orders, setOrders] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const loadOrders = async () => {
    setLoading(true);

    try {
      const response = await fetch("/api/orders?limit=5");

      if (!response.ok) {
        setOrders([]);
        return;
      }

      const data = await response.json();
      setOrders(Array.isArray(data) ? data : data.orders || []);
    } catch {
      setOrders([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="order-history-panel">
      <button
        type="button"
        className="order-history-toggle"
        onClick={() => {
          const next = !open;
          setOpen(next);
          if (next) loadOrders();
        }}
      >
        Previous Orders
      </button>

      {open && (
        <div className="order-history-card">
          <div className="order-history-header">
            <strong>Previous Orders</strong>
            <button
              type="button"
              aria-label="Close previous orders"
              onClick={() => setOpen(false)}
            >
              ×
            </button>
          </div>

          {loading && (
            <div className="order-history-empty">
              Loading orders...
            </div>
          )}

          {!loading && orders.length === 0 && (
            <div className="order-history-empty">
              No previous orders yet.
            </div>
          )}

          {!loading &&
            orders.map((order) => (
              <article
                className="order-history-item"
                key={order.order_id}
              >
                <div>
                  <strong>{order.order_id}</strong>

                  <div className="order-history-meta">
                    {formatDate(order.created_at)}
                    {order.status ? ` · ${order.status}` : ""}
                  </div>

                  {Array.isArray(order.items) && (
                    <div className="order-history-items">
                      {order.items.slice(0, 3).map((item, index) => (
                        <span key={`${order.order_id}-${index}`}>
                          {item.title || item.item_title || "Item"}
                          {item.quantity ? ` × ${item.quantity}` : ""}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  className="order-history-reorder"
                  onClick={() => onReorder(order.order_id)}
                >
                  Reorder with AI
                </button>
              </article>
            ))}
        </div>
      )}
    </section>
  );
}
