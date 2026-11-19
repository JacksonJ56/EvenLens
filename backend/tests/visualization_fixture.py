"""Explicit TEST-only complete report, validated by the real statistics pipeline."""
from datetime import datetime, timedelta, timezone
from app.public_opinion.preparation import prepare_comments
from app.public_opinion.schemas import ChartInterpretation, CommentInput, ContextInsight, ExternalSource, Group, Evidence, OverallAssessment, OpinionReport, OpinionRequest, Post, Section
from app.public_opinion.workflow import validate_report


def save_visualization_fixture(store, settings):
    at = datetime(2025, 4, 4, tzinfo=timezone.utc)
    payload = OpinionRequest(function_id='public_opinion', idempotency_key='TEST-visualization',
        selection={'category_id':'general','category_name':'综合','platform_id':'weibo','platform_name':'微博','feed_id':'hot','board_id':None,'board_name':None},
        event={'id':'TEST_visualization_event','title':'TEST 可视化验收：合成评论与背景资料','url':None,'captured_at':at})
    post = Post(id='4982041758140155',platform_id='weibo',url='https://m.weibo.cn/detail/4982041758140155',
                title='TEST 合成帖子',verification='authorized_import',published_at=at-timedelta(hours=1))
    comments = [CommentInput(platform_id='weibo',post_id=post.id,comment_id=f'TEST_c{i}',source_rank=i+1,
        content='TEST 为什么没有更多公开资料？' if i%3==0 else 'TEST 希望提供更多可靠依据。'+('测试长文本内容'*12) if i%3==1 else f'TEST 支持公开真实资料{i}',
        created_at=at+timedelta(hours=i),like_count=i%2,sort_mode='unknown') for i in range(24)]
    prepared,stats=prepare_comments([post],comments,settings)
    dataset=store.save_dataset(payload,[post],prepared,stats)
    refs=[Evidence(post_id=c.post_id,comment_id=c.comment_id) for c in prepared]
    def section(kind,title,groups,**kwargs):
        return Section(type=kind,title=title,status='completed',summary='TEST 合成场景，仅用于组件验收',sample_size=24,analyzed_sample=refs,
            data=[Group(label=label,explanation='TEST 按合成评论真实 ID 归属计算',evidence=evidence) for label,evidence in groups],**kwargs)
    sections=[section('discussion_topics','TEST 主要主题',[('TEST 信息公开',refs),('TEST 数据局限',refs[:8])]),
        section('public_emotions','TEST 情绪样本',[('担忧',refs[:8]),('中立',refs[8:])]),
        section('stance_analysis','TEST 明确议题下的立场',[('支持公开说明',refs[:8]),('需要更多依据',refs[8:])],issue='TEST 是否需要公开说明')]
    quote='TEST 合成来源原文：时间接近本身不能证明因果关系。'
    source=ExternalSource(id='TEST_source',title='TEST 背景资料',url='https://example.com/test-source',access='body',published_at='2025-04-03')
    sections.append(Section(type='contextual_insights',title='TEST 背景关联',status='completed',summary='TEST 证据展开场景',
        contextual_insights=[ContextInsight(title='TEST 时间背景关联',dimension='temporal',explanation='TEST 仅核验界面，不是真实研究结论。',classification='supported_inference',
            source_ids=[source.id],evidence=[{'source_id':source.id,'excerpt':quote}],uncertainty='TEST 不证明因果关系')]))
    sections.append(Section(type='representative_comments',title='TEST 参考原文',status='completed',summary='TEST 有限原文参考',evidence=refs[:6]))
    task,_=store.create_task(payload)
    store.save_sources(task['id'],{source.id:{**source.model_dump(),'content':quote}})
    report=OpinionReport(task_id=task['id'],dataset_id=dataset,selection=payload.selection,selected_event=payload.event,generated_at=at.isoformat(),
        status='completed',overall_assessment=OverallAssessment(status='completed',
            summary='TEST 自动化验收的合成报告，不代表真实舆情。已有讨论围绕信息公开和证据是否充分展开，表达谨慎的评论并不自动代表反对公开说明，两种关注可能同时存在。理解这些差异时，应先区分对事实的疑问、对程序的期待与已经形成的态度，避免将相似用语归为统一立场。背景资料只能帮助解释研究语境，时间接近本身不足以支持因果判断。当前评论来自有限来源且保留了接口顺序，无法排除排序、截取和资料覆盖带来的影响，因此本例仅用于验证研究报告的排版、证据关联与交互，不构成现实事件的公众意见结论。',
            core_judgment='TEST 先理解观点依据，再解释差异；不能从有限样本推断全平台共识。',
            key_findings=['TEST 关注信息公开与证据充分性。','TEST 情绪和立场需要分别理解。'],section_types=['discussion_topics','public_emotions','stance_analysis'],evidence=refs[:1],source_ids=[source.id]),
        stats=stats,sections=sections,posts=[post],sources=[source],limitations=stats.limitations,usage={})
    report=validate_report(report,store)
    prose={'discussion_topics':'TEST 评论同时提及信息公开和资料核验，主题允许交叉，不能据此划分对立人群。',
        'emotion_distribution':'TEST 表达谨慎不自动意味着反对公开信息，情绪标签须结合语境，不能扩大为平台全体态度。',
        'stance_comparison':'TEST 支持说明和希望更多依据是不同侧重，不应仅按标签制造对立阵营。',
        'comment_timeline':'TEST 时间分布受截取和接口排序影响，不能解释为整体热度变化。',
        'post_contribution':'TEST 样本集中于单个帖子，来源覆盖有限，不能外推为全平台共识。',
        'discussion_radar':'TEST 文本特征可以核验，但不能作为评论质量或操纵行为的评分。'}
    report.chart_interpretations=[ChartInterpretation(chart_id=c.id,analysis=prose[c.type],evidence=next((p.evidence[:1] for p in c.points if p.evidence),[])) for c in report.charts]
    report=validate_report(report,store)
    store.save_report(task['id'],report.model_dump(mode='json'))
    store.update_task(task['id'],status='completed',stage='finished',checkpoint={'dataset_id':dataset,'collection_done':True},message='TEST 合成报告')
    return task['id']
