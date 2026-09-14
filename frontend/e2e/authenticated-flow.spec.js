import { test, expect } from "@playwright/test";

const E2E_EMAIL = "e2e-playwright@example.com";
const E2E_PASSWORD = "E2EPassword123!";
const TOKEN_KEY = "food_agent_access_token";
const USER_KEY = "food_agent_user";

async function login(page) {
  const response = await page.request.post("/api/auth/login", {
    data: {
      email: E2E_EMAIL,
      password: E2E_PASSWORD,
    },
  });

  expect(response.ok()).toBeTruthy();

  const data = await response.json();

  expect(data.access_token).toBeTruthy();
  expect(data.user?.email).toBe(E2E_EMAIL);

  await page.goto("/");

  await page.evaluate(
    ({ tokenKey, userKey, accessToken, user }) => {
      localStorage.setItem(tokenKey, accessToken);
      localStorage.setItem(userKey, JSON.stringify(user));
    },
    {
      tokenKey: TOKEN_KEY,
      userKey: USER_KEY,
      accessToken: data.access_token,
      user: data.user,
    },
  );

  await page.reload();

  await expect
    .poll(async () => {
      return await page.evaluate(async () => {
        const response = await fetch("/api/auth/me");
        return response.status;
      });
    })
    .toBe(200);
}

async function browserApi(page, path, options = {}) {
  return await page.evaluate(
    async ({ path, options }) => {
      const token = localStorage.getItem("food_agent_access_token");

      const response = await fetch(path, {
        method: options.method || "GET",
        headers: {
          "Content-Type": "application/json",
          ...(token
            ? {
                Authorization: `Bearer ${token}`,
              }
            : {}),
          ...(options.headers || {}),
        },
        body: options.body
          ? JSON.stringify(options.body)
          : undefined,
      });

      let data = null;

      try {
        data = await response.json();
      } catch {
        data = null;
      }

      return {
        ok: response.ok,
        status: response.status,
        data,
      };
    },
    { path, options },
  );
}

test.describe("authenticated application flow", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("persists an authenticated cart across refresh", async ({ page }) => {
    const clearResponse = await browserApi(page, "/api/cart", {
      method: "DELETE",
    });

    expect(clearResponse.ok).toBeTruthy();

    const addResponse = await browserApi(page, "/api/cart/items", {
      method: "POST",
      body: {
        restaurant_name: "Test Restaurant",
        subdomain: "test",
        item_id: "item-001",
        title: "Chicken Biryani",
        quantity: 1,
        variation_id: "regular",
      },
    });

    expect(addResponse.ok).toBeTruthy();
    expect(addResponse.data.items).toHaveLength(1);
    expect(addResponse.data.items[0].item_id).toBe("item-001");
    expect(addResponse.data.items[0].variation.id).toBe("regular");

    await page.reload();

    const meResponse = await browserApi(page, "/api/auth/me");

    expect(meResponse.ok).toBeTruthy();
    expect(meResponse.data.email).toBe(E2E_EMAIL);

    const refreshedCartResponse = await browserApi(page, "/api/cart");

    expect(refreshedCartResponse.ok).toBeTruthy();
    expect(refreshedCartResponse.data.items).toHaveLength(1);
    expect(refreshedCartResponse.data.items[0].item_id).toBe("item-001");
    expect(refreshedCartResponse.data.items[0].variation.id).toBe("regular");
    expect(refreshedCartResponse.data.items[0].quantity).toBe(1);
  });

  test("authenticated checkout creates order, clears persistent cart, then cancels order", async ({
    page,
  }) => {
    const clearResponse = await browserApi(page, "/api/cart", {
      method: "DELETE",
    });

    expect(clearResponse.ok).toBeTruthy();

    const addResponse = await browserApi(page, "/api/cart/items", {
      method: "POST",
      body: {
        restaurant_name: "Test Restaurant",
        subdomain: "test",
        item_id: "item-001",
        title: "Chicken Biryani",
        quantity: 1,
        variation_id: "regular",
      },
    });

    expect(addResponse.ok).toBeTruthy();

    const checkoutResponse = await browserApi(page, "/api/cart/checkout", {
      method: "POST",
      body: {
        confirm: true,
      },
    });

    expect(checkoutResponse.ok).toBeTruthy();
    expect(checkoutResponse.data.order_id).toBeTruthy();

    const orderId = checkoutResponse.data.order_id;

    const cartAfterCheckout = await browserApi(page, "/api/cart");

    expect(cartAfterCheckout.ok).toBeTruthy();
    expect(cartAfterCheckout.data.items).toHaveLength(0);

    const cancelResponse = await browserApi(
      page,
      `/api/cart/orders/${orderId}`,
      {
        method: "DELETE",
      },
    );

    expect(cancelResponse.ok).toBeTruthy();
    expect(cancelResponse.data.status).toBe("cancelled");
  });
});
