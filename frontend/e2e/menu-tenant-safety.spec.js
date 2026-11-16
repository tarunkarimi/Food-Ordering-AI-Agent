import { test, expect } from "@playwright/test";

test("a menu response for another tenant is rejected before cart sync", async ({ page }) => {
  const unexpected = [];
  const requests = [];

  await page.addInitScript(() => {
    localStorage.setItem("food_agent_access_token", "synthetic-menu-token");
    localStorage.setItem(
      "food_agent_user",
      JSON.stringify({ id: 999005, email: "menu-tenant@example.test" }),
    );
  });

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.startsWith("/api/")) requests.push(`${request.method()} ${path}`);

    if (path === "/api/auth/me" && request.method() === "GET") {
      await route.fulfill({
        json: { id: 999005, email: "menu-tenant@example.test" },
      });
      return;
    }
    if (path === "/menu-api/" && request.method() === "GET") {
      expect(url.searchParams.get("subdomain")).toBe("test");
      await route.fulfill({
        json: {
          restaurant_name: "Duplicate Display Name",
          subdomain: "another-tenant",
          items: [{ id: "wrong-item", title: "Wrong Tenant Food", base_price: 1 }],
        },
      });
      return;
    }
    if (path.startsWith("/api/")) {
      unexpected.push(`${request.method()} ${path}`);
      await route.fulfill({ status: 501, json: { detail: "Unexpected request." } });
      return;
    }
    if (url.origin === "http://127.0.0.1:5173") {
      await route.continue();
      return;
    }
    unexpected.push(`${request.method()} ${url.origin}${path}`);
    await route.abort();
  });

  await page.goto("/");

  await expect(
    page.getByText("Could not verify the restaurant menu. Please try again later.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("Wrong Tenant Food", { exact: true })).toHaveCount(0);
  expect(requests.every((entry) => entry === "GET /api/auth/me")).toBeTruthy();
  expect(requests.length).toBeGreaterThan(0);
  expect(unexpected).toEqual([]);
});
