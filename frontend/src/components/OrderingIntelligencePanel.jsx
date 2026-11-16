import { useCallback, useState } from "react";
import {
  Brain,
  ChevronDown,
  ChevronUp,
  Loader2,
  RefreshCw,
  Sparkles,
  Star,
} from "lucide-react";

const AI_API = import.meta.env.VITE_AI_API_URL || "";
const REQUEST_TIMEOUT_MS = 15000;

async function fetchWithTimeout(url, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(),
    REQUEST_TIMEOUT_MS
  );

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("The request timed out.");
    }

    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

function getAuthHeaders() {
  const token = localStorage.getItem("food_agent_access_token");

  return token
    ? {
        Authorization: `Bearer ${token}`,
      }
    : {};
}

function formatDate(value) {
  if (!value) return "";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function OrderingIntelligencePanel({ restaurantName, subdomain }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [intelligence, setIntelligence] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [error, setError] = useState("");

  const loadIntelligence = useCallback(async () => {
    try {
      setLoading(true);
      setError("");

      const intelligenceParams = new URLSearchParams();
      if (restaurantName) intelligenceParams.set("restaurant_name", restaurantName);
      if (subdomain) intelligenceParams.set("subdomain", subdomain);
      const intelligenceQuery = intelligenceParams.toString();
      const restaurantQuery = intelligenceQuery
        ? `?${intelligenceQuery}`
        : "";

      const suggestionsParams = new URLSearchParams({ limit: "5" });
      if (restaurantName) suggestionsParams.set("restaurant_name", restaurantName);
      if (subdomain) suggestionsParams.set("subdomain", subdomain);
      const suggestionsQuery = `?${suggestionsParams.toString()}`;

      const headers = getAuthHeaders();

      const [intelligenceResponse, suggestionsResponse] =
        await Promise.all([
          fetchWithTimeout(
            `${AI_API}/api/ordering-intelligence${restaurantQuery}`,
            { headers }
          ),
          fetchWithTimeout(
            `${AI_API}/api/ordering-intelligence/reorder-suggestions${suggestionsQuery}`,
            { headers }
          ),
        ]);

      const intelligenceData = await intelligenceResponse.json();
      const suggestionsData = await suggestionsResponse.json();

      if (!intelligenceResponse.ok) {
        throw new Error("Unable to load ordering intelligence.");
      }

      if (!suggestionsResponse.ok) {
        throw new Error("Unable to load reorder suggestions.");
      }

      setIntelligence(intelligenceData);

      setSuggestions(
        Array.isArray(suggestionsData?.suggestions)
          ? suggestionsData.suggestions
          : []
      );
    } catch (loadError) {
      console.warn("Ordering intelligence request failed.");

      setError(
        loadError?.message ||
          "Unable to load your ordering intelligence."
      );
    } finally {
      setLoading(false);
    }
  }, [restaurantName, subdomain]);

  const handleToggle = () => {
    const nextOpen = !open;

    setOpen(nextOpen);

    if (
      nextOpen &&
      !intelligence &&
      !loading
    ) {
      void loadIntelligence();
    }
  };

  const usualItems = Array.isArray(
    intelligence?.usual_items
  )
    ? intelligence.usual_items
    : [];

  const favoriteRestaurants = Array.isArray(
    intelligence?.favorite_restaurants
  )
    ? intelligence.favorite_restaurants
    : [];

  const repeatCombinations = Array.isArray(
    intelligence?.repeat_combinations
  )
    ? intelligence.repeat_combinations
    : [];

  const latestOrder = intelligence?.latest_order;

  return (
    <section
      className="cart-card"
      style={{
        marginBottom: "16px",
        overflow: "hidden",
      }}
    >
      <div
        className="card-title"
        style={{
          cursor: "pointer",
          alignItems: "center",
        }}
        onClick={handleToggle}
      >
        <div>
          <p className="eyebrow">
            AI INSIGHTS
          </p>

          <h3
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <Brain size={19} />
            Ordering Intelligence
          </h3>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          {intelligence?.orders_analyzed !== undefined && (
            <span>
              {intelligence.orders_analyzed} orders
            </span>
          )}

          {open && (
            <button
              type="button"
              aria-label="Refresh ordering intelligence"
              onClick={(event) => {
                event.stopPropagation();
                void loadIntelligence();
              }}
              disabled={loading}
              style={{
                border: "0",
                background: "transparent",
                color: "#a8a8b2",
                cursor: loading
                  ? "default"
                  : "pointer",
                display: "flex",
                padding: "4px",
              }}
            >
              {loading ? (
                <Loader2
                  className="spin"
                  size={16}
                />
              ) : (
                <RefreshCw size={16} />
              )}
            </button>
          )}

          {open ? (
            <ChevronUp size={17} />
          ) : (
            <ChevronDown size={17} />
          )}
        </div>
      </div>

      {open && (
        <div style={{ marginTop: "16px" }}>
          {loading ? (
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                padding: "20px 0",
              }}
            >
              <Loader2
                className="spin"
                size={22}
              />
            </div>
          ) : error ? (
            <div
              style={{
                padding: "14px",
                borderRadius: "12px",
                background:
                  "rgba(255,255,255,0.04)",
                color: "#a8a8b2",
                fontSize: "13px",
              }}
            >
              <div>{error}</div>

              <button
                type="button"
                className="add-button"
                onClick={() =>
                  void loadIntelligence()
                }
                style={{ marginTop: "10px" }}
              >
                Try Again
              </button>
            </div>
          ) : !intelligence?.orders_analyzed ? (
            <div
              style={{
                padding: "14px",
                borderRadius: "12px",
                background:
                  "rgba(255,255,255,0.04)",
                color: "#a8a8b2",
                fontSize: "13px",
                lineHeight: 1.5,
              }}
            >
              <Sparkles
                size={18}
                style={{ marginBottom: "7px" }}
              />

              <div>
                Place a few orders and I&apos;ll
                learn your favorites, repeat
                combinations, and reorder patterns.
              </div>
            </div>
          ) : (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "16px",
              }}
            >
              {suggestions.length > 0 && (
                <div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "7px",
                      marginBottom: "9px",
                    }}
                  >
                    <Sparkles size={15} />

                    <strong
                      style={{ fontSize: "14px" }}
                    >
                      Smart Reorder
                    </strong>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "7px",
                    }}
                  >
                    {suggestions
                      .slice(0, 5)
                      .map((item) => (
                        <div
                          key={item.title}
                          style={{
                            display: "flex",
                            justifyContent:
                              "space-between",
                            alignItems: "center",
                            gap: "12px",
                            padding: "10px 12px",
                            borderRadius: "11px",
                            background:
                              "rgba(139,61,255,0.08)",
                            border:
                              "1px solid rgba(139,61,255,0.16)",
                          }}
                        >
                          <div
                            style={{
                              minWidth: 0,
                            }}
                          >
                            <strong
                              style={{
                                display: "block",
                                fontSize: "13px",
                                overflow: "hidden",
                                textOverflow:
                                  "ellipsis",
                                whiteSpace:
                                  "nowrap",
                              }}
                            >
                              {item.title}
                            </strong>

                            <span
                              style={{
                                color: "#8f8f99",
                                fontSize: "11px",
                              }}
                            >
                              {item.reason}
                            </span>
                          </div>

                          <span
                            style={{
                              fontSize: "11px",
                              color: "#b5b5bf",
                              whiteSpace:
                                "nowrap",
                            }}
                          >
                            {item.total_quantity}× total
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {usualItems.length > 0 && (
                <div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "7px",
                      marginBottom: "9px",
                    }}
                  >
                    <Star size={15} />

                    <strong
                      style={{ fontSize: "14px" }}
                    >
                      Your Favorites
                    </strong>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: "7px",
                    }}
                  >
                    {usualItems
                      .slice(0, 6)
                      .map((item) => (
                        <span
                          key={item.title}
                          style={{
                            padding: "7px 9px",
                            borderRadius: "999px",
                            background:
                              "rgba(255,255,255,0.05)",
                            border:
                              "1px solid rgba(255,255,255,0.08)",
                            fontSize: "11px",
                            color: "#c7c7cf",
                          }}
                        >
                          {item.title} ·{" "}
                          {item.order_count}×
                        </span>
                      ))}
                  </div>
                </div>
              )}

              {repeatCombinations.length > 0 && (
                <div>
                  <div
                    style={{
                      marginBottom: "8px",
                      fontSize: "14px",
                      fontWeight: 700,
                    }}
                  >
                    Repeat Combos
                  </div>

                  {repeatCombinations
                    .slice(0, 3)
                    .map((combo) => (
                      <div
                        key={combo.items.join("|")}
                        style={{
                          padding: "9px 11px",
                          marginBottom: "6px",
                          borderRadius: "10px",
                          background:
                            "rgba(255,255,255,0.04)",
                          color: "#bdbdc6",
                          fontSize: "12px",
                        }}
                      >
                        {combo.items.join(" + ")}

                        <span
                          style={{
                            color: "#85858f",
                          }}
                        >
                          {" "}
                          · {combo.order_count}×
                        </span>
                      </div>
                    ))}
                </div>
              )}

              {favoriteRestaurants.length > 0 && (
                <div
                  style={{
                    paddingTop: "12px",
                    borderTop:
                      "1px solid rgba(255,255,255,0.07)",
                  }}
                >
                  <div
                    style={{
                      fontSize: "12px",
                      color: "#85858f",
                      marginBottom: "5px",
                    }}
                  >
                    Favorite restaurant
                  </div>

                  <strong
                    style={{ fontSize: "14px" }}
                  >
                    {
                      favoriteRestaurants[0]
                        .restaurant_name
                    }
                  </strong>

                  <span
                    style={{
                      color: "#85858f",
                      fontSize: "11px",
                      marginLeft: "7px",
                    }}
                  >
                    {
                      favoriteRestaurants[0]
                        .order_count
                    }{" "}
                    orders
                  </span>
                </div>
              )}

              {latestOrder && (
                <div
                  style={{
                    paddingTop: "12px",
                    borderTop:
                      "1px solid rgba(255,255,255,0.07)",
                    color: "#85858f",
                    fontSize: "11px",
                  }}
                >
                  Latest order:{" "}
                  <strong
                    style={{ color: "#bdbdc6" }}
                  >
                    {latestOrder.order_id}
                  </strong>

                  {latestOrder.created_at && (
                    <>
                      {" "}
                      ·{" "}
                      {formatDate(
                        latestOrder.created_at
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default OrderingIntelligencePanel;
