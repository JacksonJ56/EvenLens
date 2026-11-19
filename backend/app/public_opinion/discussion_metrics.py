"""Interpretable binary comment features, not LLM-generated influence/controversy scores."""
from collections import Counter
from .schemas import ChartPoint, Evidence, OpinionChart


def discussion_metrics(report, roots):
    analyzed = {(ref.post_id, ref.comment_id) for section in report.sections
                if section.status in {'completed', 'insufficient_data'}
                for ref in section.analyzed_sample}
    sample = {key: value for key, value in roots.items() if key in analyzed}
    if len(sample) < 20:
        return None
    # Stored content has already been HTML/Unicode-normalized by preparation.py.
    repeated = Counter(row['content'].strip() for row in sample.values())
    definitions = [
        ('question_mark', '含问号文本', '清洗后的文字含中文或英文问号；仅为标点特征，不等同真实疑问或质疑立场。',
         lambda row: '?' in row['content'] or '？' in row['content']),
        ('long_text', '较长文本', '清洗并去除首尾空白后的文字不少于 50 个 Unicode 字符；不推断评论质量。',
         lambda row: len(row['content'].strip()) >= 50),
        ('repeated_text', '同文重复', '本次已分析样本中，清洗后文字完全相同且出现至少两次；每条独立评论都保留，不判断机器人或水军。',
         lambda row: repeated[row['content'].strip()] >= 2),
    ]
    # Missing likes are unknown, never silently interpreted as zero.
    if all(isinstance(row.get('like_count'), int) and not isinstance(row['like_count'], bool) and row['like_count'] >= 0 for row in sample.values()):
        definitions.append(('liked', '获赞评论', '采集时点赞数大于 0；只有样本全部提供可靠点赞数时才计算，不代表平台总互动。', lambda row: row['like_count'] > 0))
    points = []
    for key, label, definition, predicate in definitions:
        refs = [Evidence(post_id=p, comment_id=c) for (p, c), row in sample.items() if predicate(row)]
        points.append(ChartPoint(id=key, label=label, count=len(refs), percent=round(len(refs) / len(sample) * 100, 1),
            explanation=definition, metric_definition=definition, evidence=refs))
    if not any(point.count for point in points):
        return None
    return OpinionChart(id='discussion-features', type='discussion_radar', title='已分析样本的文本与互动特征',
        description='仅统计已完成分析的一级评论；各轴均为满足明确定义的评论数 ÷ 同一实际样本量 × 100%，范围 0–100%。指标可重叠，不相加为 100%，不是影响力、争议度或全平台评分。',
        sample_size=len(sample), points=points, unit='%', overlapping=True, normalization='comment_share')
