import { test, expect } from "@playwright/test";

const TEST_USER = {
  id: 999004,
  email: "authenticated-flow@example.test",
  phone: null,
};
const TEST_TOKEN = "synthetic-authenticated-flow-token";
const E2E_EMAIL = TEST_USER.email;
const TOKEN_KEY = "food_agent_access_token";
const USER_KEY = "food_agent_user";
const ITEM = {
  item_id: "synthetic-item-001",
  title: "Synthetic Chicken Biryani",
  base_price: 12,
  quantity: 1,
  variation: { id: "regular", name: "Regular" },
};

async function installMockServer(page) {
  const state = {
    cart: [],
    orders: [],
    unexpected: [],
    requests: [],
  };

  await page.addInitScript(
    ({ tokenKey, userKey, token, user }) => {
      localStorage.setItem(tokenKey, token);
      localStorage.setItem(userKey, JSON.stringify(user));
    },
    { tokenKey: TOKEN_KEY, userKey: USER_KEY, token: TEST_TOKEN, user: TEST_USER },
  );

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (path.startsWith("/api/")) {
      state.requests.push(`${method} ${path}`);
    }

    if (path === "/api/auth/me" && method === "GET") {
      await route.fulfill({ json: TEST_USER });
      return;
    }
    if (path === "/menu-api/" && method === "GET") {
      if (url.searchParams.get("subdomain") !== "test") {
        state.unexpected.push(`${method} ${path} invalid tenant`);
        await route.fulfill({ status: 400, json: { detail: "Invalid tenant" } });
        return;
      }
      await route.fulfill({
        json: {
          restaurant_name: "Synthetic Test Restaurant",
          subdomain: "test",
          items: [{ id: ITEM.item_id, ...ITEM }],
        },
      });
      return;
    }
    if (path === "/api/chats/state" && method === "GET") {
      await route.fulfill({ json: { cart: { items: [] } } });
      return;
    }
    if (path === "/api/orders" && method === "GET") {
      await route.fulfill({ json: { orders: state.orders } });
      return;
    }
    if (path === "/api/cart" && method === "GET") {
      await route.fulfill({ json: { items: state.cart } });
      return;
    }
    if (path === "/api/cart" && method === "DELETE") {
      state.cart = [];
      await route.fulfill({ json: { success: true, items: [] } });
      return;
    }
    if (path === "/api/cart/items" && method === "POST") {
      const body = request.postDataJSON();
      const existing = state.cart.find((line) => line.item_id === body.item_id);
      if (existing) existing.quantity += body.quantity;
      else state.cart.push({ ...ITEM, ...body, variation: ITEM.variation });
      await route.fulfill({ json: { items: state.cart } });
      return;
    }
    if (path === "/api/cart/checkout" && method === "POST") {
      const body = request.postDataJSON();
      if (body.confirm !== true || state.cart.length === 0) {
        await route.fulfill({ status: 400, json: { detail: "Checkout not confirmed." } });
        return;
      }
      const order = {
        order_id: "SYNTHETIC-ORDER-001",
        status: "confirmed",
        subtotal: state.cart.reduce((sum, line) => sum + line.base_price * line.quantity, 0),
      };
      state.orders.push(order);
      state.cart = [];
      await route.fulfill({ json: order });
      return;
    }
    if (path.startsWith("/api/cart/orders/") && method === "DELETE") {
      const orderId = path.split("/").at(-1);
      const order = state.orders.find((entry) => entry.order_id === orderId);
      if (!order) {
        await route.fulfill({ status: 404, json: { detail: "Order was not found." } });
        return;
      }
      order.status = "cancelled";
      await route.fulfill({ json: { success: true, order_id: orderId, status: order.status } });
      return;
    }
    if (path.startsWith("/api/")) {
      state.unexpected.push(`${method} ${path}`);
      await route.fulfill({ status: 501, json: { detail: "Unexpected isolated E2E request." } });
      return;
    }
    if (url.origin === "http://127.0.0.1:5173") {
      await route.continue();
      return;
    }
    state.unexpected.push(`${method} ${url.origin}${path}`);
    await route.abort();
  });

  return state;
}

async function browserApi(page, path, options = {}) {
  return page.evaluate(async ({ path, options }) => {
    const token = localStorage.getItem("food_agent_access_token");
    const response = await fetch(path, {
      method: options.method || "GET",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    let data = null;
    try { data = await response.json(); } catch { data = null; }
    return { ok: response.ok, status: response.status, data };
  }, { path, options });
}

test.describe("authenticated application flow with isolated services", () => {
  test("restores a synthetic authenticated cart after refresh", async ({ page }) => {
    const mock = await installMockServer(page);
    await page.goto("/");

    expect((await browserApi(page, "/api/cart", { method: "DELETE" })).ok).toBeTruthy();
    const add = await browserApi(page, "/api/cart/items", {
      method: "POST",
      body: {
        restaurant_name: "Synthetic Test Restaurant",
        subdomain: "test",
        item_id: ITEM.item_id,
        title: ITEM.title,
        quantity: 1,
        variation_id: "regular",
      },
    });
    expect(add.ok).toBeTruthy();
    await page.reload();

    const me = await browserApi(page, "/api/auth/me");
    const cart = await browserApi(page, "/api/cart");
    expect(me.data.email).toBe(E2E_EMAIL);
    expect(cart.data.items).toHaveLength(1);
    expect(cart.data.items[0].item_id).toBe(ITEM.item_id);
    expect(cart.data.items[0].quantity).toBe(1);
    expect(mock.unexpected).toEqual([]);
  });

  test("mocked checkout and cancellation stay inside the synthetic API", async ({ page }) => {
    const mock = await installMockServer(page);
    await page.goto("/");

    const add = await browserApi(page, "/api/cart/items", {
      method: "POST",
      body: {
        restaurant_name: "Synthetic Test Restaurant",
        subdomain: "test",
        item_id: ITEM.item_id,
        title: ITEM.title,
        quantity: 1,
        variation_id: "regular",
      },
    });
    expect(add.ok).toBeTruthy();

    const checkout = await browserApi(page, "/api/cart/checkout", {
      method: "POST",
      body: { confirm: true },
    });
    expect(checkout.ok).toBeTruthy();
    expect(checkout.data.order_id).toBe("SYNTHETIC-ORDER-001");
    expect((await browserApi(page, "/api/cart")).data.items).toHaveLength(0);

    const cancel = await browserApi(page, "/api/cart/orders/SYNTHETIC-ORDER-001", {
      method: "DELETE",
    });
    expect(cancel.ok).toBeTruthy();
    expect(cancel.data.status).toBe("cancelled");
    expect(mock.unexpected).toEqual([]);
    expect(mock.requests.filter((entry) => entry.includes("checkout"))).toHaveLength(1);
  });
});
