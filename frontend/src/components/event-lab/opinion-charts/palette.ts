import type { OpinionChart, OpinionChartPoint } from "@/types/public-opinion";
const emotionColors: Record<string, string> = { 愤怒: "var(--opinion-anger)", 担忧: "var(--opinion-worry)", 喜悦: "var(--opinion-joy)", 同情: "var(--opinion-empathy)", 悲伤: "var(--opinion-sadness)", 中立: "var(--opinion-neutral)", 无法判断: "var(--opinion-unknown)" };
export function pointColor(chart: OpinionChart, point: OpinionChartPoint, index: number) {
  return chart.type === "emotion_distribution" ? emotionColors[point.label] ?? "var(--opinion-unknown)" : `var(--opinion-series-${index % 5})`;
}
