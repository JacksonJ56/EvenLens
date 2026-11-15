import { Aperture, Github, Music2, PawPrint, Radar, TvMinimalPlay, Zap } from "lucide-react";
import type { PlatformId } from "@/types/trending";

const glyphs = {
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
};

export function PlatformIcon({ id }: { id: PlatformId }) {
  return <span className="platform-icon" data-platform={id} aria-hidden="true">{glyphs[id]}</span>;
}
