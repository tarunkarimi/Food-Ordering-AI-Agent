import { test, expect } from "@playwright/test";

const ACCESS_TOKEN_KEY = "food_agent_access_token";
const USER_KEY = "food_agent_user";
const TEST_USER = {
  id: 999002,
  email: "cart-smoke@example.test",
  phone: null,
};
const MENU_ITEM = {
  id: "smoke-item-001",
  title: "Cart Smoke Noodles",
  description: "A deterministic menu item for the browser smoke test.",
  base_price: 7.5,
};

function cartState(items) {
  return {
    cart: {
      items: items.map((item) => ({
        item_id: item.item_id,
        title: item.title,
        units: [
          {
            key: `${item.item_id}|no_variant`,
            quantity: item.quantity,
            base_price: item.base_price,
            variation: null,
          },
        ],
      })),
    },
  };
}

// FastAPI serializes LangGraph's StateSnapshot as a tuple-like JSON array:
// `values` is element zero. Keep this fixture aligned with GET /api/chats/state.
function stateSnapshot(items) {
  return [cartState(items), [], {}, {}, null, null, [], []];
}

test("authenticated user can add, retain, and remove a menu item", async ({
  page,
}) => {
  const mockCart = new Map();
  const unexpectedRequests = [];
  const intercepted = new Set();
  const cartRequests = [];
  const stateSessions = [];

  await page.addInitScript(
    ({ tokenKey, userKey, user }) => {
      localStorage.setItem(tokenKey, "playwright-mock-token");
      localStorage.setItem(userKey, JSON.stringify(user));
    },
    {
      tokenKey: ACCESS_TOKEN_KEY,
      userKey: USER_KEY,
      user: TEST_USER,
    },
  );

  // This route is both the deterministic API fixture and a network guard:
  // only Vite's same-origin assets may pass through to the local dev server.
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (pathname.endsWith("/api/auth/me") && request.method() === "GET") {
      intercepted.add("auth");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(TEST_USER),
      });
      return;
    }

    if (
      url.searchParams.get("subdomain") === "test" &&
      !pathname.includes("/api/")
    ) {
      intercepted.add("menu");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          restaurant_name: "Smoke Test Restaurant",
          subdomain: "test",
          items: [MENU_ITEM],
        }),
      });
      return;
    }

    if (pathname.endsWith("/api/chats/state") && request.method() === "GET") {
      intercepted.add("cart-state");
      const sessionId = url.searchParams.get("session_id");
      stateSessions.push({
        sessionId,
        restaurantName: url.searchParams.get("restaurant_name"),
        subdomain: url.searchParams.get("subdomain"),
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          stateSnapshot(Array.from(mockCart.get(sessionId)?.values() || [])),
        ),
      });
      return;
    }

    if (
      (pathname.endsWith("/api/chats/cart/add") ||
        pathname.endsWith("/api/chats/cart/remove")) &&
      request.method() === "POST"
    ) {
      const isAdd = pathname.endsWith("/add");
      const action = isAdd ? "cart-add" : "cart-remove";
      intercepted.add(action);

      const body = request.postDataJSON();
      cartRequests.push({ action, body });
      const sessionCart = mockCart.get(body.session_id) || new Map();
      const current = sessionCart.get(body.item_id);

      if (isAdd) {
        sessionCart.set(body.item_id, {
          item_id: body.item_id,
          title: body.title,
          quantity: (current?.quantity || 0) + body.quantity,
          base_price: MENU_ITEM.base_price,
        });
      } else if (current) {
        const remaining = current.quantity - body.quantity;
        if (remaining > 0) {
          sessionCart.set(body.item_id, { ...current, quantity: remaining });
        } else {
          sessionCart.delete(body.item_id);
        }
      }

      mockCart.set(body.session_id, sessionCart);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ success: true }),
      });
      return;
    }

    if (pathname.includes("/api/")) {
      unexpectedRequests.push(`${request.method()} ${pathname}`);
      await route.fulfill({
        status: 501,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Unexpected API request in isolated smoke test." }),
      });
      return;
    }

    if (url.origin === "http://127.0.0.1:5173") {
      await route.continue();
      return;
    }

    unexpectedRequests.push(`${request.method()} ${url.origin}${pathname}`);
    await route.abort();
  });

  await page.goto("/");

  await expect(page.getByText(TEST_USER.email, { exact: true })).toBeVisible();
  await expect(page.getByText("Smoke Test Restaurant", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: MENU_ITEM.title })).toBeVisible();
  await expect(page.getByText("Your cart is empty", { exact: true })).toBeVisible();

  const menuItem = page.getByRole("article").filter({ hasText: MENU_ITEM.title });
  await menuItem.getByRole("button", { name: "Add" }).click();

  const cartItem = page.locator(".cart-item").filter({ hasText: MENU_ITEM.title });
  await expect(cartItem).toBeVisible();
  await expect(cartItem.getByText("1", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("complementary").getByText("1 items", { exact: true }),
  ).toBeVisible();

  await page.reload();
  const persistedItem = page.locator(".cart-item").filter({ hasText: MENU_ITEM.title });
  await expect(page.getByText(TEST_USER.email, { exact: true })).toBeVisible();
  await expect(persistedItem).toBeVisible();
  await expect(persistedItem.getByText("1", { exact: true })).toBeVisible();

  await persistedItem.locator("button.delete-button").click();
  await expect(page.getByText("Your cart is empty", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("complementary").getByText("0 items", { exact: true }),
  ).toBeVisible();

  await page.reload();
  await expect(page.getByText(TEST_USER.email, { exact: true })).toBeVisible();
  await expect(page.getByText("Your cart is empty", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("complementary").getByText("0 items", { exact: true }),
  ).toBeVisible();

  expect([...intercepted].sort()).toEqual([
    "auth",
    "cart-add",
    "cart-remove",
    "cart-state",
    "menu",
  ]);
  expect(stateSessions.length).toBeGreaterThanOrEqual(4);
  expect(new Set(stateSessions.map(({ sessionId }) => sessionId)).size).toBe(1);
  expect(stateSessions.every(({ sessionId, restaurantName, subdomain }) =>
    Boolean(sessionId) &&
    restaurantName === "Smoke Test Restaurant" &&
    subdomain === "test"
  )).toBe(true);
  expect(cartRequests).toEqual([
    {
      action: "cart-add",
      body: {
        session_id: stateSessions[0].sessionId,
        restaurant_name: "Smoke Test Restaurant",
        subdomain: "test",
        item_id: MENU_ITEM.id,
        title: MENU_ITEM.title,
        quantity: 1,
        variation_id: null,
      },
    },
    {
      action: "cart-remove",
      body: {
        session_id: stateSessions[0].sessionId,
        restaurant_name: "Smoke Test Restaurant",
        subdomain: "test",
        item_id: MENU_ITEM.id,
        title: MENU_ITEM.title,
        quantity: 1,
        variation_id: "no_variant",
      },
    },
  ]);
  expect(unexpectedRequests).toEqual([]);
});
