import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EventLens · 事件透镜",
  description: "浏览多平台热点，借助 AI 梳理事件脉络、角色背景与争议观点。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
