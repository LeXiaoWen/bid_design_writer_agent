import { expect, test } from "@playwright/test";

const project = {
  id: "project-1",
  title: "默认项目",
  workspace_path: null,
  created_at: "2026-01-01T00:00:00.000Z",
  updated_at: "2026-01-01T00:00:00.000Z",
};

const profile = {
  id: "profile-1",
  provider: "OpenAI",
  display_name: "OpenAI",
  base_url: "https://api.openai.com/v1",
  model: "gpt-4o",
  has_key: true,
  created_at: "2026-01-01T00:00:00.000Z",
  updated_at: "2026-01-01T00:00:00.000Z",
};

async function mockApi(page: import("@playwright/test").Page) {
  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (pathname === "/api/v1/auth/status") return json({ authenticated: false, registration_allowed: true });
    if (pathname === "/api/v1/auth/login" && method === "POST") return json({ token: "test-token" });
    if (pathname === "/api/v1/me") return json({ id: "user-1", username: "tester", created_at: "2026-01-01T00:00:00.000Z" });
    if (pathname === "/api/v1/projects") return json([project]);
    if (pathname === "/api/v1/conversations") return json([]);
    if (pathname === "/api/v1/provider-profiles") return json([profile]);
    if (pathname === "/api/v1/web-search-config") return json({ provider: "tavily", has_key: true, source: "system", max_results: 5, search_depth: "basic" });
    return json({ detail: `Unexpected API request: ${method} ${pathname}` }, 500);
  });
}

test("登录后可通过键盘打开和关闭带标签的配置与账号对话框", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");

  await page.getByLabel("用户名").fill("tester");
  await page.getByLabel("密码").fill("test-password");
  await page.getByRole("button", { name: "登录" }).click();

  const configButton = page.getByRole("button", { name: "模型配置" });
  await expect(configButton).toBeVisible();
  await configButton.click();
  const configDialog = page.getByRole("dialog", { name: "模型与工具配置" });
  await expect(configDialog).toBeVisible();
  await expect(configDialog.getByLabel("API key", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(configDialog).toBeHidden();

  await page.getByRole("button", { name: /tester/ }).click();
  const accountDialog = page.getByRole("dialog", { name: "账号" });
  await expect(accountDialog).toBeVisible();
  await expect(accountDialog.getByLabel("当前密码")).toHaveAttribute("autocomplete", "current-password");
  await expect(accountDialog.getByLabel("新密码", { exact: true })).toHaveAttribute("autocomplete", "new-password");
  await page.keyboard.press("Escape");
  await expect(accountDialog).toBeHidden();
});
