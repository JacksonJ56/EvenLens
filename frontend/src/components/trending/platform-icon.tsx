import { Aperture, Github, Music2, PawPrint, Radar, TvMinimalPlay, Zap } from "lucide-react";
import type { PlatformId } from "@/types/trending";

const glyphs: Partial<Record<PlatformId, React.ReactNode>> = {
  weibo: <Radar size="1em" />,
  zhihu: "知",
  baidu: <PawPrint size="1em" />,
  ithome: "IT",
  hupu: "虎",
  bilibili: <TvMinimalPlay size="1em" />,
  xiaohongshu: "小红书",
  douyin: <Music2 size="1em" />,
  "36kr": "36",
  xueqiu: <Aperture size="1em" />,
  github: <Github size="1em" />,
  juejin: <Zap size="1em" />,
  cctv: "央", zaobao: "早", chinadaily: "CD", tieba: "贴", sspai: "少",
  jiqizhixin: "机", huxiu: "嗅", agirls: "獺", "douban-media": "豆", "douban-community": "豆",
  hongguo: "果", gamersky: "游", tonghuashun: "同", eastmoney: "财",
  wallstreetcn: "见", huggingface: "HF", "52pojie": "52", infoq: "IQ",
};

export function PlatformIcon({ id }: { id: PlatformId }) {
  return <span className="platform-icon" data-platform={id} aria-hidden="true">{glyphs[id]}</span>;
}
