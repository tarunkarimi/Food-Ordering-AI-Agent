const TOKEN_KEY = "food_agent_access_token";
const USER_KEY = "food_agent_user";

export function getAccessToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser() {
  const raw = localStorage.getItem(USER_KEY);

  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw);
  } catch {
    localStorage.removeItem(USER_KEY);
    return null;
  }
}

export function saveAuth(data) {
  if (!data?.access_token || !data?.user) {
    throw new Error("Invalid authentication response.");
  }

  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(USER_KEY, JSON.stringify(data.user));
}

export function saveUser(user) {
  if (!user) {
    localStorage.removeItem(USER_KEY);
    return;
  }

  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export async function apiRequest(
  path,
  options = {},
  timeoutMs = 15000
) {
  const controller = new AbortController();

  const timeoutId = setTimeout(
    () => controller.abort(),
    timeoutMs
  );

  try {
    const headers = new Headers(options.headers || {});

    if (
      options.body !== undefined &&
      !headers.has("Content-Type")
    ) {
      headers.set("Content-Type", "application/json");
    }

    const token = getAccessToken();

    if (token) {
      headers.set(
        "Authorization",
        `Bearer ${token}`
      );
    }

    return await fetch(path, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(
        "The request timed out. Please try again."
      );
    }

    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

/*
 * Existing App.jsx already uses fetch("/api/...").
 * Install one centralized interceptor so the existing application
 * automatically becomes authenticated without duplicating auth
 * headers throughout the ordering UI.
 */
const originalFetch = window.fetch.bind(window);

if (!window.__foodAgentAuthenticatedFetchInstalled) {
  window.fetch = (input, init = {}) => {
    const url =
      typeof input === "string"
        ? input
        : input?.url || "";

    const isApiRequest =
      url.startsWith("/api/") ||
      url.startsWith("/api?");

    if (!isApiRequest) {
      return originalFetch(input, init);
    }

    const headers = new Headers(
      init.headers ||
        (input instanceof Request
          ? input.headers
          : undefined)
    );

    const token = getAccessToken();

    if (token) {
      headers.set(
        "Authorization",
        `Bearer ${token}`
      );
    } else {
      headers.delete("Authorization");
    }

    return originalFetch(input, {
      ...init,
      headers,
    }).then((response) => {
      if (
        response.status === 401 &&
        token &&
        isApiRequest &&
        !url.startsWith("/api/auth/")
      ) {
        clearAuth();
        window.dispatchEvent(
          new CustomEvent("food-agent-auth-expired")
        );
      }

      return response;
    });
  };

  window.__foodAgentAuthenticatedFetchInstalled = true;
}
