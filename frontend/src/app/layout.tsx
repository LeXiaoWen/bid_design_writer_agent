import type { Metadata } from "next";
import "github-markdown-css/github-markdown-light.css";
import "highlight.js/styles/github.css";
import "./globals.css";
import { AppProviders } from "./providers";

export const metadata: Metadata = {
  title: "建筑设计标书方案助手",
  description: "建筑设计标书方案编写与 OpenAI-compatible 流式聊天工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body><AppProviders>{children}</AppProviders></body>
    </html>
  );
}
