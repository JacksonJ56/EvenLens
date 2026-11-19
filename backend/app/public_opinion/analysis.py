"""Batched semantic analysis with validated assignments and deterministic counts."""
import hashlib
import json
import re
from collections import defaultdict

from pydantic import Field

from ..event_trace.schemas import Schema
from .llm import structured
from .prompts import BATCH, SAFETY
from .schemas import Evidence, Group, Section

EMOTIONS = {"愤怒", "担忧", "喜悦", "同情", "悲伤", "中立", "无法判断"}
TITLES = {"discussion_topics": "主要讨论主题", "public_emotions": "公众情绪反馈", "opinion_clusters": "主要观点",
          "stance_analysis": "明确议题下的立场", "controversies": "争议焦点", "trends": "样本时间观察"}


def non_statistical(text: str, fallback: str) -> str:
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|％|条|人|成|倍|位)|百分之[一二三四五六七八九十百零〇\d]+", text):
        return fallback
    return text


class BatchGroup(Schema):
    label: str = Field(min_length=1, max_length=100)
    explanation: str = Field(max_length=1200)
    comment_refs: list[str] = Field(max_length=50)


class BatchOutput(Schema):
    applicable: bool
    reason: str = Field(max_length=800)
    groups: list[BatchGroup] = Field(max_length=20)


class MergeItem(Schema):
    group_key: str
    canonical_label: str = Field(max_length=100)


class MergeOutput(Schema):
    mapping: list[MergeItem] = Field(max_length=600)


def comment_ref(comment):
    return hashlib.sha256((comment["post_id"] + "\0" + comment["comment_id"]).encode()).hexdigest()[:20]


def batches(comments, max_bytes, max_chars=1200):
    batch, size = [], 0
    for comment in comments:
        if comment.get("parent_comment_id"):
            continue
        text = comment["content"][:max_chars].encode()[:max(100, max_bytes - 1000)].decode(errors="ignore")
        item = {"ref": comment_ref(comment), "content": text,
                "post_id": comment["post_id"], "source_rank": comment["source_rank"], "created_at": comment["created_at"]}
        length = len(json.dumps(item, ensure_ascii=False).encode())
        if batch and (len(batch) >= 35 or size + length > max_bytes):
            yield batch
            batch, size = [], 0
        batch.append(item)
        size += length
    if batch:
        yield batch


class CommentAnalysis:
    PROMPT_VERSION = "opinion-v2-topics"

    def __init__(self, store, dataset_id, model, settings):
        self.store, self.dataset_id, self.model, self.settings = store, dataset_id, model, settings
        self.comments = store.read_comments(dataset_id)
        self.refs = {comment_ref(c): c for c in self.comments if not c["parent_comment_id"]}
        self.sections = {}
        self.event_context = {}

    async def analyze(self, kind: str, issue: str = "") -> dict:
        if kind in self.sections:
            return self.compact(self.sections[kind])
        if kind == "stance_analysis" and not issue.strip():
            return {"error": "立场分析须提供可从评论中确认的明确议题"}
        if kind == "trends":
            dates = {c["created_at"][:10] for c in self.comments if c["created_at"] and not c["parent_comment_id"]}
            if len(dates) < 3:
                section = Section(type=kind, title=TITLES[kind], status="insufficient_data", summary="评论时间覆盖不足。",
                                  reason="至少需要三个日期的数据；热门/前排截取仍不支持总体趋势推断。")
                self.sections[kind] = section
                return self.compact(section)
            by_date = defaultdict(list)
            for comment in self.comments:
                if not comment["parent_comment_id"]:
                    by_date[comment["created_at"][:10] if comment["created_at"] else "时间未知"].append(comment)
            section = Section(type=kind, title=TITLES[kind], status="completed",
                summary="仅显示本次样本按保存日期的分布，前排截取不能支持全平台趋势推断。",
                reason="未做随机采样，各日期数量受平台排序和采集时点影响。", sample_size=len(self.refs),
                data=[Group(label=date, explanation="该日期下实际保留的一级评论。", count=len(cs),
                      evidence=[Evidence(post_id=c["post_id"], comment_id=c["comment_id"]) for c in cs])
                      for date, cs in sorted(by_date.items())][:40])
            self.sections[kind] = section
            return self.compact(section)
        all_groups, reasons, examined = [], [], set()
        partial = False
        for batch_index, batch in enumerate(batches(self.comments, self.settings.batch_bytes, self.settings.comment_chars)):
            payload = {"task": kind, "issue": issue[:300], "event_context": self.event_context, "comments": batch}
            key = hashlib.sha256(json.dumps([self.PROMPT_VERSION, self.model.model_name, getattr(self.model, "openai_api_base", ""), payload],
                                ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            cached = self.store.cache_get(key)
            try:
                if cached:
                    output = BatchOutput.model_validate(cached)
                else:
                    output = await structured(self.model, BATCH, payload, BatchOutput)
                    self.store.cache_put(key, output.model_dump())
            except Exception:
                partial = True
                reasons.append("模型预算、超时或批次输出失败，仅保留已完成批次。")
                break
            examined.update(c["ref"] for c in batch)
            if not output.applicable:
                reasons.append(output.reason)
                continue
            allowed, assigned = {c["ref"] for c in batch}, set()
            for i, group in enumerate(output.groups):
                if kind == "public_emotions" and group.label not in EMOTIONS:
                    continue
                refs = [ref for ref in dict.fromkeys(group.comment_refs)
                        if ref in allowed and (kind == "discussion_topics" or ref not in assigned)]
                assigned.update(refs)
                if refs:
                    all_groups.append({"key": f"b{batch_index}g{i}", "label": non_statistical(group.label, "未核实的主题描述"),
                                       "explanation": non_statistical(group.explanation, "数量请以本模块的实际样本统计为准。"), "refs": refs})
            if kind == "public_emotions":
                unknown = allowed - assigned
                if unknown:
                    all_groups.append({"key": f"b{batch_index}unknown", "label": "无法判断", "explanation": "未能可靠分类",
                                       "refs": sorted(unknown)})
        analyzed_sample = [Evidence(post_id=c["post_id"], comment_id=c["comment_id"]) for r, c in self.refs.items() if r in examined]
        if not all_groups:
            section = Section(type=kind, title=TITLES[kind], status="failed" if not examined else "insufficient_data" if partial else "not_applicable",
                              summary="当前样本未能形成此项分析。", sample_size=len(examined), analyzed_sample=analyzed_sample,
                              reason="；".join(reasons)[:1000] or "缺少可核查的评论依据")
            self.sections[kind] = section
            return self.compact(section)
        labels = {g["key"]: g["label"] for g in all_groups}
        if kind != "public_emotions" and len(set(labels.values())) > 1:
            # Merge only names, never regenerate counts or assignments.
            canonical = []
            # Bounded incremental label merge; never pass an unbounded list of batch summaries.
            for start in range(0, len(all_groups), 25):
                chunk = all_groups[start:start + 25]
                merge_data = {"existing_labels": canonical[:40],
                              "groups": [{"key": g["key"], "label": g["label"], "explanation": g["explanation"][:120]} for g in chunk]}
                merge_key = hashlib.sha256(json.dumps([self.PROMPT_VERSION, self.model.model_name,
                                           getattr(self.model, "openai_api_base", ""), kind, merge_data],
                                           sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                cached_merge = self.store.cache_get(merge_key)
                try:
                    merged = MergeOutput.model_validate(cached_merge) if cached_merge else await structured(self.model,
                        SAFETY + "将含义相同的跨批次主题/观点归并为统一标签，优先复用已有标签，保留不同观点。只返回输入 key 到标签的映射。",
                        merge_data, MergeOutput)
                except Exception:
                    partial = True
                    reasons.append("跨批次标签未完整归并，相近主题可能仍分列。")
                    break
                self.store.cache_put(merge_key, merged.model_dump())
                keys = {g["key"] for g in chunk}
                labels.update({m.group_key: non_statistical(m.canonical_label, "未核实的主题描述") for m in merged.mapping if m.group_key in keys and m.canonical_label})
                canonical = list(dict.fromkeys([*canonical, *(labels[g["key"]] for g in chunk)]))
        grouped, explanations = defaultdict(set), {}
        for g in all_groups:
            label = labels[g["key"]]
            grouped[label].update(g["refs"])
            explanations.setdefault(label, g["explanation"])
        denominator = len(examined)
        groups = [Group(label=label, explanation=explanations[label], count=len(refs),
                        percent=round(len(refs) / denominator * 100, 1) if denominator else None,
                        evidence=[Evidence(post_id=c["post_id"], comment_id=c["comment_id"])
                                  for r, c in self.refs.items() if r in refs]) for label, refs in grouped.items()]
        groups.sort(key=lambda g: -g.count)
        if len(groups) > 40:
            reasons.append("仅展示按样本归属数量排序的前 40 项。")
        section = Section(type=kind, title=TITLES[kind], status="insufficient_data" if partial else "completed",
                          summary="按实际完成分析的一级评论批次归纳；数量由有效评论归属计算。",
                          data=groups[:40], sample_size=denominator, analyzed_sample=analyzed_sample,
                          reason="；".join(reasons)[:1000] or None,
                          issue=issue[:300] if kind == "stance_analysis" else None)
        self.sections[kind] = section
        return self.compact(section)

    @staticmethod
    def compact(section):
        value = section.model_dump()
        value.pop("analyzed_sample", None)  # The harness never receives the full assignment list.
        for group in value["data"]:
            group["evidence"] = group["evidence"][:4]
        return value
