import { test, expect } from "@playwright/test";

const ACCESS_TOKEN_KEY = "food_agent_access_token";
const USER_KEY = "food_agent_user";

const TEST_USER = {
  id: 999001,
  email: "e2e@example.com",
  phone: null,
};

test("authenticated session survives browser refresh", async ({ page }) => {
  const unexpectedRequests = [];
  await page.addInitScript(
    ({ tokenKey, userKey, user }) => {
      localStorage.setItem(tokenKey, "e2e-valid-token");
      localStorage.setItem(userKey, JSON.stringify(user));
    },
    {
      tokenKey: ACCESS_TOKEN_KEY,
      userKey: USER_KEY,
      user: TEST_USER,
    },
  );

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) {
      unexpectedRequests.push(`${request.method()} ${url.pathname}`);
      await route.abort();
      return;
    }
    if (url.origin === "http://127.0.0.1:5173") {
      await route.continue();
      return;
    }
    unexpectedRequests.push(`${request.method()} ${url.origin}${url.pathname}`);
    await route.abort();
  });

  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(TEST_USER),
    });
  });

  await page.route("**/api/chats/state*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ cart: { items: [] } }),
    });
  });

  await page.route("**/menu-api/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        restaurant_name: "Session Test Restaurant",
        subdomain: "test",
        items: [],
      }),
    });
  });

  await page.goto("/");

  await expect(
    page.getByText("e2e@example.com", { exact: true }),
  ).toBeVisible();

  await page.reload();

  await expect(
    page.getByText("e2e@example.com", { exact: true }),
  ).toBeVisible();

  await expect(page.getByText("Restoring your session...")).toHaveCount(0);
  expect(unexpectedRequests).toEqual([]);
});

test("expired authenticated session returns user to login", async ({ page }) => {
  const unexpectedRequests = [];
  await page.addInitScript(
    ({ tokenKey, userKey, user }) => {
      localStorage.setItem(tokenKey, "e2e-expired-token");
      localStorage.setItem(userKey, JSON.stringify(user));
    },
    {
      tokenKey: ACCESS_TOKEN_KEY,
      userKey: USER_KEY,
      user: TEST_USER,
    },
  );

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) {
      unexpectedRequests.push(`${request.method()} ${url.pathname}`);
      await route.abort();
      return;
    }
    if (url.origin === "http://127.0.0.1:5173") {
      await route.continue();
      return;
    }
    unexpectedRequests.push(`${request.method()} ${url.origin}${url.pathname}`);
    await route.abort();
  });

  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(TEST_USER),
    });
  });

  await page.route("**/menu-api/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        restaurant_name: "Session Test Restaurant",
        subdomain: "test",
        items: [],
      }),
    });
  });

  await page.route("**/api/chats/**", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "Session expired",
      }),
    });
  });

  await page.goto("/");

  await expect(
    page.getByText("e2e@example.com", { exact: true }),
  ).toBeVisible();

  await page.evaluate(async () => {
    await fetch("/api/chats/e2e-session");
  });

  await expect(
    page.getByText(
      "Your session has expired. Please sign in again.",
      { exact: true },
    ),
  ).toBeVisible();

  await expect(page.getByText("Welcome back")).toBeVisible();

  const token = await page.evaluate(
    (key) => localStorage.getItem(key),
    ACCESS_TOKEN_KEY,
  );

  expect(token).toBeNull();

  const user = await page.evaluate(
    (key) => localStorage.getItem(key),
    USER_KEY,
  );

  expect(user).toBeNull();
  expect(unexpectedRequests).toEqual([]);
});
