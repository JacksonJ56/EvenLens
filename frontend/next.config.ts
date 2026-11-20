import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  devIndicators: false,
  async rewrites() {
    const backend = (process.env.EVENTLENS_BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
    return [{ source: "/api/boards/:platform/:board", destination: `${backend}/api/boards/:platform/:board` }];
  },
};

export default nextConfig;
