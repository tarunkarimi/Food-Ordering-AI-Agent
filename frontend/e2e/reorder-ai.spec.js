import { test, expect } from "@playwright/test";

test("reorder with AI sends the previous order through the AI chat flow", async ({
  page,
}) => {
  const orderId = "TEST-REORDER-001";
  const assistantMessage =
    "I prepared your previous order in your current cart using today's menu and prices.";

  await page.addInitScript(() => {
    localStorage.setItem("food_agent_access_token", "test-token");
    localStorage.setItem(
      "food_agent_user",
      JSON.stringify({ id: 1, email: "test@example.com" })
    );
    localStorage.setItem("food_agent_session", "reorder-e2e-session");
  });

  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        email: "test@example.com",
      }),
    });
  });

  await page.route("**/api/orders*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        orders: [
          {
            order_id: orderId,
            status: "confirmed",
            created_at: "2026-09-08T10:00:00Z",
            items: [
              {
                title: "Chicken Biryani",
                quantity: 2,
              },
            ],
          },
        ],
      }),
    });
  });

  await page.route("**/api/chats/state*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          cart: {
            items: [],
          },
        },
      ]),
    });
  });

  await page.route("**/api/chats/orders*", async (route) => {
    const request = route.request();
    const body = request.postDataJSON();

    expect(body.user_message).toBe(`Reorder order ${orderId}`);
    expect(body.session_id).toBe("reorder-e2e-session");

    const sseBody =
      `data: ${JSON.stringify({ content: assistantMessage })}\n\n` +
      "data: [DONE]\n\n";

    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sseBody,
    });
  });

  await page.route("**/menu-api/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        restaurant_name: "Test Restaurant",
        items: [],
      }),
    });
  });

  await page.goto("/");

  const previousOrdersButton = page.getByRole("button", {
    name: "Previous Orders",
  });

  await expect(previousOrdersButton).toBeVisible();

  await previousOrdersButton.click();

  await expect(page.getByText(orderId)).toBeVisible();

  await page.getByRole("button", {
    name: "Reorder with AI",
  }).click();

  await expect(
    page.getByText(`Reorder order ${orderId}`)
  ).toBeVisible();

  await expect(page.getByText(assistantMessage)).toBeVisible();
});
