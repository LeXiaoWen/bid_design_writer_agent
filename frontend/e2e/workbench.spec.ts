import { expect, test } from "@playwright/test";
import type { BidWorkflow } from "../src/lib/types";

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

async function mockBidWorkflowApi(page: import("@playwright/test").Page) {
  const conversation = {
    id: "conversation-1",
    project_id: project.id,
    title: "测试招标",
    provider_profile_id: profile.id,
    model: profile.model,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
  };
  const workflow = {
    id: "workflow-1",
    project_id: project.id,
    conversation_id: conversation.id,
    provider_profile_id: profile.id,
    file_name: "测试招标.txt",
    extracted_markdown: "",
    confirmation_text: "",
    template_choice: null,
    status: "extracting",
    error: null,
    execution: {
      state: "running",
      phase: "extraction",
      progress: 35,
      message: "正在解析招标文件第 2/3 块。",
    },
    artifacts: [],
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
  };
  let conversationCreated = false;

  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (pathname === "/api/v1/auth/status") return json({ authenticated: false, registration_allowed: true });
    if (pathname === "/api/v1/auth/login" && method === "POST") return json({ token: "test-token" });
    if (pathname === "/api/v1/me") return json({ id: "user-1", username: "tester", created_at: "2026-01-01T00:00:00.000Z" });
    if (pathname === "/api/v1/projects") return json([project]);
    if (pathname === "/api/v1/provider-profiles") return json([profile]);
    if (pathname === "/api/v1/web-search-config") return json({ provider: "tavily", has_key: true, source: "system", max_results: 5, search_depth: "basic" });
    if (pathname === "/api/v1/conversations" && method === "POST") {
      conversationCreated = true;
      return json(conversation);
    }
    if (pathname === "/api/v1/conversations") return json(conversationCreated ? [conversation] : []);
    if (pathname === `/api/v1/conversations/${conversation.id}/messages`) {
      return json(conversationCreated ? [
        { id: "message-user", conversation_id: conversation.id, role: "user", content: "已上传招标文件：测试招标.txt", status: "completed", created_at: "2026-01-01T00:00:00.000Z", updated_at: "2026-01-01T00:00:00.000Z" },
        { id: "message-assistant", conversation_id: conversation.id, role: "assistant", content: "正在执行阶段一信息提取。", status: "completed", created_at: "2026-01-01T00:00:01.000Z", updated_at: "2026-01-01T00:00:01.000Z" },
      ] : []);
    }
    if (pathname === "/api/v1/bid-workflows" && method === "POST") {
      return json({ ...workflow, status: "uploaded", execution: { state: "queued", phase: "extraction", progress: 0, message: "等待执行。" }, char_count: 12, message: "文件解析完成。" });
    }
    if (pathname === "/api/v1/bid-workflows") return json(conversationCreated ? [workflow] : []);
    if (pathname === `/api/v1/bid-workflows/${workflow.id}` && method === "GET") return json(workflow);
    if (pathname === `/api/v1/bid-workflows/${workflow.id}/extract` && method === "POST") return json({ workflow, message: "阶段一信息提取已开始。" });
    if (pathname === `/api/v1/bid-workflows/${workflow.id}/stream`) return route.fulfill({ contentType: "text/event-stream", body: "" });
    return json({ detail: `Unexpected API request: ${method} ${pathname}` }, 500);
  });
}

async function mockCompletedBidWorkflowApi(page: import("@playwright/test").Page) {
  const conversation = {
    id: "conversation-stage-two",
    project_id: project.id,
    title: "阶段二测试",
    provider_profile_id: profile.id,
    model: profile.model,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
  };
  let workflow: BidWorkflow = {
    id: "workflow-stage-two",
    project_id: project.id,
    conversation_id: conversation.id,
    provider_profile_id: profile.id,
    file_name: "阶段二招标.txt",
    extracted_markdown: "# 招标文件信息提取",
    confirmation_text: "",
    template_choice: null,
    status: "extraction_ready",
    error: null,
    execution: { state: "completed", phase: "extraction", progress: 100, message: "阶段一信息提取完成。" },
    artifacts: [],
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
  };
  const messages = [
    { id: "stage-two-user", conversation_id: conversation.id, role: "user", content: "已上传招标文件：阶段二招标.txt", status: "completed", created_at: "2026-01-01T00:00:00.000Z", updated_at: "2026-01-01T00:00:00.000Z" },
    { id: "stage-two-assistant", conversation_id: conversation.id, role: "assistant", content: "阶段一信息提取已完成。", status: "completed", created_at: "2026-01-01T00:00:01.000Z", updated_at: "2026-01-01T00:00:01.000Z" },
  ];

  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (pathname === "/api/v1/auth/status") return json({ authenticated: false, registration_allowed: true });
    if (pathname === "/api/v1/auth/login" && method === "POST") return json({ token: "test-token" });
    if (pathname === "/api/v1/me") return json({ id: "user-1", username: "tester", created_at: "2026-01-01T00:00:00.000Z" });
    if (pathname === "/api/v1/projects") return json([project]);
    if (pathname === "/api/v1/conversations") return json([conversation]);
    if (pathname === `/api/v1/conversations/${conversation.id}/messages`) return json(messages);
    if (pathname === "/api/v1/provider-profiles") return json([profile]);
    if (pathname === "/api/v1/web-search-config") return json({ provider: "tavily", has_key: true, source: "system", max_results: 5, search_depth: "basic" });
    if (pathname === "/api/v1/bid-workflows") return json([workflow]);
    if (pathname === `/api/v1/bid-workflows/${workflow.id}`) return json(workflow);
    if (pathname === `/api/v1/bid-workflows/${workflow.id}/confirm` && method === "POST") {
      workflow = { ...workflow, confirmation_text: "确认", execution: { state: "completed", phase: "extraction", progress: 100, message: "阶段一已确认。" } };
      return json({ workflow, message: "阶段一信息已确认。" });
    }
    if (pathname === `/api/v1/bid-workflows/${workflow.id}/generate` && method === "POST") {
      workflow = {
        ...workflow,
        status: "completed",
        execution: { state: "completed", phase: "generation", progress: 100, message: "任务已完成。" },
        artifacts: [
          { name: "阶段二测试_设计方案.md", size: 128, kind: "proposal" },
          { name: "阶段二测试_绘图提示词.md", size: 64, kind: "drawing" },
        ],
      };
      return json({ workflow, message: "阶段二设计方案生成已开始。" });
    }
    if (pathname.endsWith("/versions/diff")) {
      return json({
        name: "阶段二测试_设计方案.md",
        base_version: 1,
        compare_version: 2,
        lines: [
          { kind: "removed", content: "旧策略" },
          { kind: "added", content: "新策略" },
        ],
      });
    }
    if (pathname.endsWith("/versions")) {
      return json([
        { name: "阶段二测试_设计方案.md", version: 2, size: 156, created_at: "2026-01-01T00:01:00.000Z" },
        { name: "阶段二测试_设计方案.md", version: 1, size: 128, created_at: "2026-01-01T00:00:00.000Z" },
      ]);
    }
    if (pathname.endsWith("/rewrite-section") && method === "POST") {
      return json({ name: "阶段二测试_设计方案.md", size: 156, kind: "proposal" });
    }
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

test("上传招标文件后自动触发阶段一并显示持久化执行进度", async ({ page }) => {
  await mockBidWorkflowApi(page);
  await page.goto("/");

  await page.getByLabel("用户名").fill("tester");
  await page.getByLabel("密码").fill("test-password");
  await page.getByRole("button", { name: "登录" }).click();

  await page.locator('input[type="file"]').setInputFiles({
    name: "测试招标.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("项目名称：测试招标"),
  });

  await expect(page.getByText("正在解析招标文件第 2/3 块。 35%", { exact: true })).toBeVisible();
  await expect(page.getByText("测试招标.txt", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "取消" })).toBeVisible();
});

test("确认阶段一后可完成阶段二并展示成果下载入口", async ({ page }) => {
  await mockCompletedBidWorkflowApi(page);
  await page.goto("/");

  await page.getByLabel("用户名").fill("tester");
  await page.getByLabel("密码").fill("test-password");
  await page.getByRole("button", { name: "登录" }).click();

  await expect(page.getByRole("button", { name: "确认阶段一" })).toBeVisible();
  await page.getByRole("button", { name: "确认阶段一" }).click();
  await expect(page.getByRole("button", { name: "生成设计方案" })).toBeVisible();
  await page.getByRole("button", { name: "生成设计方案" }).click();

  await expect(page.getByText("任务已完成。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载 Markdown 文件" })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载 ZIP 包" })).toBeVisible();
  await expect(page.getByRole("button", { name: "阶段二测试_设计方案.md" })).toBeVisible();

  await page.getByRole("button", { name: "AI 改章节" }).first().click();
  await page.getByLabel("阶段二测试_设计方案.md 章节标题").fill("总体策略");
  await page.getByLabel("阶段二测试_设计方案.md 章节修改要求").fill("加强低碳设计");
  const rewriteRequest = page.waitForRequest((request) => new URL(request.url()).pathname.endsWith("/rewrite-section"));
  await page.getByRole("button", { name: "仅重写此章节" }).click();
  expect((await rewriteRequest).postDataJSON()).toEqual({ heading: "总体策略", instruction: "加强低碳设计" });

  await page.getByRole("button", { name: "版本" }).first().click();
  await expect(page.getByText("v1 → v2 差异", { exact: true })).toBeVisible();
  await expect(page.getByText("+ 新策略", { exact: true })).toBeVisible();
  await expect(page.getByText("- 旧策略", { exact: true })).toBeVisible();
});
