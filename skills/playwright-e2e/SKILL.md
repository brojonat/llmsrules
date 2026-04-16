---
name: playwright-e2e
description: Write Playwright end-to-end tests for web apps. Use when setting up e2e tests, testing auth flows, or writing browser automation scripts. Covers project setup, test patterns, auth bypass for dev mode, and integration with Go/backend servers.
---

# Playwright E2E Testing

Write complete Playwright test scripts rather than navigating interactively via MCP tools. The agent already knows the app's DOM from the codebase, so it can generate full tests in one shot — reusable, repeatable, no inference per step.

This approach comes from Armin Ronacher (creator of Flask) and Mario Zechner (creator of libGDX), who both advocate for code generation over interactive MCP tool calls for testing your own app.

## Project setup

```bash
mkdir e2e && cd e2e
npm init -y
npm install @playwright/test
npx playwright install chromium
```

Minimal `playwright.config.js`:

```js
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  testMatch: "*.spec.js",
  timeout: 30000,
  use: {
    baseURL: process.env.BASE_URL || "http://localhost:8080",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "cd .. && go run .",
    url: "http://localhost:8080/healthz",
    timeout: 15000,
    reuseExistingServer: true,
    env: {
      PORT: "8080",
      BASE_URL: "http://localhost:8080",
      SECRET_KEY: "e2e-test-secret",
      DB_PATH: ":memory:",
    },
  },
});
```

Key settings:
- `webServer` auto-starts the backend with test-specific env vars
- `reuseExistingServer: true` skips startup if something's already on the port
- `DB_PATH: ":memory:"` gives each test run a fresh database
- `screenshot` and `trace` only on failure to keep runs fast

Add to Makefile:

```makefile
test-e2e:
	cd e2e && npx playwright test
```

Add to `.gitignore`:

```
node_modules/
test-results/
```

## Auth bypass pattern for testing

The biggest challenge in e2e tests is completing auth flows that involve email (magic links, OTPs, etc.). You can't receive emails in a headless browser.

**Solution**: in dev mode (e.g., when `SMTP_HOST` is unset), return the auth token directly in the API response. Tests call the API, extract the token, and navigate to the verify URL.

Backend (Go example):

```go
resp := map[string]any{
    "ok":      true,
    "message": "Check your email!",
}
// In dev mode, include the token so e2e tests can complete verification
if cfg.SMTPHost == "" {
    resp["token"] = token
    resp["verify_url"] = magicLink
}
```

Test helper:

```js
async function requestMagicLink(request, baseURL, email) {
  const resp = await request.post(`${baseURL}/api/request-link`, {
    data: { email },
  });
  const data = await resp.json();
  if (!data.token) {
    throw new Error("No token — server must be in dev mode");
  }
  return data.token;
}
```

Test usage:

```js
test("full auth flow", async ({ page, request }) => {
  const token = await requestMagicLink(request, BASE, "jane@company.com");
  await page.goto(`/api/verify?token=${token}`);
  // Now authenticated — session cookie is set
  await expect(page.locator("#main-content")).toBeVisible();
});
```

This token is never exposed in production. The gate is the same env var that controls whether real emails are sent.

## JWT helper for admin API tests

If your app uses JWT-protected admin endpoints, generate tokens in the test helper:

```js
const crypto = require("crypto");

function getAdminJWT(secret) {
  const header = Buffer.from(
    JSON.stringify({ alg: "HS256", typ: "JWT" })
  ).toString("base64url");
  const now = Math.floor(Date.now() / 1000);
  const claims = Buffer.from(
    JSON.stringify({ sub: "admin", iat: now, exp: now + 300 })
  ).toString("base64url");

  const sigInput = `${header}.${claims}`;
  const sig = crypto
    .createHmac("sha256", secret)
    .update(sigInput)
    .digest("base64url");
  return `${sigInput}.${sig}`;
}
```

Use in tests:

```js
test("admin endpoint requires auth", async ({ request }) => {
  const resp = await request.get(`${BASE}/admin/stats`);
  expect(resp.status()).toBe(401);
});

test("admin endpoint works with valid JWT", async ({ request }) => {
  const jwt = getAdminJWT("e2e-test-secret");
  const resp = await request.get(`${BASE}/admin/stats`, {
    headers: { Authorization: `Bearer ${jwt}` },
  });
  const data = await resp.json();
  expect(data).toHaveProperty("total_votes");
});
```

## Test structure patterns

### Reset state before each test

```js
test.beforeEach(async ({ request }) => {
  const jwt = getAdminJWT(SECRET);
  await request.post(`${BASE}/admin/reset`, {
    headers: { Authorization: `Bearer ${jwt}` },
    data: { confirm: "RESET" },
  });
});
```

### Mix API calls and browser interactions

Use `request` (Playwright's built-in HTTP client) for setup/teardown and API-only tests. Use `page` for browser interactions. They share the same cookie jar per context.

```js
test("seed data then check UI", async ({ page, request }) => {
  // API: seed test data
  await seedVotes(request, BASE, "google.com", 50);

  // Browser: verify it shows up
  await page.goto("/");
  await expect(page.locator("text=Google")).toBeVisible();
});
```

### Test the full user journey in one test

Don't over-split. One test that covers verify → action → result → return visit is more valuable than four isolated tests, because it catches state transition bugs:

```js
test("verify → smash → cooldown on reload", async ({ page, request }) => {
  const token = await requestMagicLink(request, BASE, "jane@company.com");
  await page.goto(`/api/verify?token=${token}`);

  // Should see the main action
  await expect(page.locator("#action-button")).toBeVisible();
  await page.click("#action-button");

  // Should see success
  await expect(page.locator("#success-screen")).toBeVisible();

  // Reload — should see the "already done" state
  await page.goto("/");
  await expect(page.locator("#already-done-screen")).toBeVisible();
});
```

### API-only tests for non-UI logic

Many things don't need a browser — admin endpoints, auth rejection, data export:

```js
test.describe("Admin API", () => {
  test("rejects unauthenticated requests", async ({ request }) => {
    const resp = await request.get(`${BASE}/admin/stats`);
    expect(resp.status()).toBe(401);
  });

  test("export filters by time window", async ({ request }) => {
    await seedVotes(request, BASE, "google.com", 10);
    const jwt = getAdminJWT(SECRET);
    const resp = await request.get(`${BASE}/admin/export?since=7d`, {
      headers: { Authorization: `Bearer ${jwt}` },
    });
    const data = await resp.json();
    expect(data.window).toBe("7d");
    expect(data.total_votes).toBe(10);
  });
});
```

## Gotchas

- **`npx playwright install chromium`** must be run after `npm install`. The npm package doesn't include browser binaries — they're downloaded separately to `~/.cache/ms-playwright/`.
- **`reuseExistingServer: true`** in the webServer config means the tests will use whatever's already on the port. Kill stale servers before running: `lsof -ti :8080 | xargs kill -9`.
- **Cookies are per-context, not per-page.** If you verify a user via `request`, the session cookie is available to `page` in the same test. But separate tests get separate contexts (clean state).
- **Don't use MCP tools for testing your own app.** The Playwright MCP (21 tools, ~13k tokens of context) is for navigating unknown pages. For your own app, write complete scripts — the agent knows the DOM from the codebase.
- **Screenshots are expensive.** Use `screenshot: "only-on-failure"` and `trace: "retain-on-failure"`. Don't screenshot every step.
- **`DB_PATH: ":memory:"` in webServer env** gives a fresh DB per test run. But the same server instance is reused across tests — use `beforeEach` to reset state if tests depend on clean data.
