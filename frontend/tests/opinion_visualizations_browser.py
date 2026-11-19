"""Browser contract test against an existing saved report; NEVER starts a paid Agent.

Run with a Python env containing playwright:
  python tests/opinion_visualizations_browser.py --base http://127.0.0.1:3101 --task TASK_ID
Only the browser's board snapshot and task-create response are replayed from the saved
report. Report, chart statistics and comment drill-down use the real local API.
"""
import argparse
import asyncio
import json
from pathlib import Path
from urllib.request import urlopen

from playwright.async_api import async_playwright


async def run(base, task_id, api_base=None):
    source = api_base or base
    report = json.load(urlopen(f'{source}/api/public-opinion/tasks/{task_id}/report'))
    progress = json.load(urlopen(f'{source}/api/public-opinion/tasks/{task_id}'))
    assert len(report['charts']) >= 2, 'Choose an existing report with classified comments'
    event = report['selected_event']
    saved_board = {'items': [{'id': event['id'], 'title': event['title'], 'rank': event.get('rank') or 1,
                  'platform': report['selection']['platform_id'], 'url': event.get('url') or ''}],
                  'mode': 'live', 'status': 'fresh', 'sourceTitle': 'Browser test: saved real event snapshot'}
    errors, requests = [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
        page = await context.new_page()
        page.set_default_timeout(12000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append(request.url) if any(value in request.url for value in ['chart-comments', '/evidence?', '/comments?']) else None)
        if api_base:
            # Optional explicit TEST server supplies a complete synthetic stance/context case.
            from urllib.parse import urlsplit
            async def fixture_api(route):
                parsed = urlsplit(route.request.url)
                response = await route.fetch(url=api_base + parsed.path + ('?' + parsed.query if parsed.query else ''))
                await route.fulfill(response=response)
            await page.route('**/api/public-opinion/tasks/**', fixture_api)
        # Chart testing is independent of live login; login has a separate browser suite.
        await page.route('**/api/public-opinion/sessions/**', lambda route: route.fulfill(json={
            'platform_id': report['selection']['platform_id'], 'status': 'verified', 'message': 'TEST session',
            'configured': True, 'session_verified': True, 'collector_ready': True, 'runtime_ready': True,
            'login_available': True, 'remote_verification_supported': True, 'job_id': None, 'checked_at': None}))
        await page.route('**/api/boards/**', lambda route: route.fulfill(json=saved_board))
        # This interception is a guard: the test cannot spend search/LLM credits.
        await page.route('**/api/public-opinion/tasks', lambda route: route.fulfill(json=progress, status=202))
        await page.goto(base)
        await page.get_by_role('button', name='事件实验室', exact=True).click()
        async def choose(label, value):
            await page.get_by_role('combobox', name=label, exact=True).click()
            await page.get_by_role('option').filter(has_text=value).first.click()
        await choose('热点分区', report['selection']['category_name'])
        await choose('热点平台', report['selection']['platform_name'])
        if await page.get_by_role('combobox', name='榜单选择', exact=True).count():
            await choose('榜单选择', report['selection']['board_name'])
        await choose('热点事件', event['title'])
        await choose('实验功能', '公众舆情分析')
        await page.get_by_role('button', name='执行', exact=True).click()
        topics = page.locator('[data-chart="discussion_topics"]')
        await topics.locator('.recharts-surface').wait_for()
        assert not requests, 'Evidence must stay unloaded until the user asks for it'
        assessment = page.get_by_role('region', name='AI 总体评价', exact=True)
        await assessment.get_by_role('heading', name='AI 总体评价', exact=True).wait_for()
        first_stats = page.locator('[data-report-section="stats"]')
        assert (await assessment.bounding_box())['y'] < (await first_stats.bounding_box())['y'], 'Statistics appeared before the assessment'
        await assessment.scroll_into_view_if_needed()
        await page.screenshot(path='/tmp/eventlens-assessment-first.png')
        representatives = page.get_by_role('region', name='代表性评论与证据', exact=True)
        if await representatives.count():
            assert await representatives.locator('details[open]').count() == 0
        async def stats_list(chart):
            summary = chart.get_by_text('查看统计明细与筛选', exact=False)
            parent = summary.locator('..')
            if await parent.get_attribute('open') is None: await summary.click()
        async def full_comment(panel):
            summary = panel.locator('details details > summary').first
            await summary.wait_for()
            assert await summary.locator('span').first.evaluate('(element) => getComputedStyle(element).webkitLineClamp') == '2'
            await summary.click()
            await panel.locator('blockquote').first.wait_for()
        if await representatives.count():
            await representatives.locator('details > summary').first.click()
            await full_comment(representatives)
            assert await representatives.locator('blockquote').count() == 1
            assert await representatives.locator('details details').count() <= 3
            if await representatives.get_by_role('button', name='下一页').is_enabled():
                await representatives.get_by_role('button', name='下一页').click()
                await full_comment(representatives)
                assert await representatives.get_by_role('button', name='上一页').is_enabled()
            await representatives.locator('details > summary').first.click()
        figure = await topics.locator('[data-chart-figure]').bounding_box()
        explanation = await topics.locator('[data-chart-analysis]').bounding_box()
        if figure and explanation and explanation['x'] > figure['x']:
            assert .39 < figure['width'] / (figure['width'] + explanation['width']) < .48
        emotion = page.locator('[data-chart="emotion_distribution"]')
        if await emotion.count():
            # Hover the ring itself; a sector's bounding-box center can be in the donut hole.
            surface = emotion.locator('svg.recharts-surface')
            bounds = await surface.bounding_box()
            await surface.hover(position={'x': bounds['width'] / 2 + 82, 'y': 115})
            await emotion.get_by_text('点击查看评论', exact=False).wait_for()
            await stats_list(emotion)
            await emotion.locator('[aria-label$="数据与评论筛选"]').get_by_role('button').first.click()
            panel = emotion.get_by_role('region')
            await full_comment(panel)
            assert await panel.locator('a[target="_blank"]').count() > 0
            if await panel.get_by_role('button', name='下一页').is_enabled():
                await panel.get_by_role('button', name='下一页').click()
                await full_comment(panel)
                assert await panel.get_by_role('button', name='上一页').is_enabled()
            await emotion.get_by_role('button', name='收起评论').click()
        await topics.locator('.recharts-bar-rectangle').first.click()
        panel = topics.get_by_role('region')
        await full_comment(panel)
        assert requests, 'Bar click must query actual comment API'
        # Keyboard equivalent for chart selection.
        await topics.get_by_role('button', name='收起评论').click()
        await stats_list(topics)
        button = topics.locator('[aria-label$="数据与评论筛选"]').get_by_role('button').first
        await button.focus(); await page.keyboard.press('Enter')
        await full_comment(topics.get_by_role('region'))
        await topics.get_by_role('button', name='收起评论').click()
        for kind in ['comment_timeline', 'post_contribution']:
            chart = page.locator(f'[data-chart="{kind}"]')
            if await chart.count():
                await stats_list(chart)
                await chart.locator('[aria-label$="数据与评论筛选"]').get_by_role('button').first.click()
                await full_comment(chart.get_by_role('region'))
                await chart.get_by_role('button', name='收起评论').click()
                if kind == 'comment_timeline':
                    expected = next(c for c in report['charts'] if c['type'] == kind)
                    assert await chart.locator('.recharts-line-dots circle').count() == len(expected['points']), 'Time series was truncated'
        stance = page.locator('[data-chart="stance_comparison"]')
        if await stance.count():
            await stance.locator('.recharts-bar-rectangle').first.hover()
            await stance.get_by_text('点击查看评论', exact=False).wait_for()
            await stance.locator('.recharts-bar-rectangle').first.click()
            await full_comment(stance.get_by_role('region'))
            await stance.get_by_role('button', name='收起评论').click()
        radar = page.locator('[data-chart="discussion_radar"]')
        if await radar.count():
            await radar.get_by_role('button', name='雷达图', exact=True).click()
            await radar.locator('.recharts-radar').wait_for()
            await radar.get_by_role('button', name='柱状图', exact=True).click()
            await radar.locator('.recharts-bar').first.wait_for()
            await stats_list(radar)
            metric = next(p for c in report['charts'] if c['type'] == 'discussion_radar' for p in c['points'] if p['count'] > 0)
            await radar.locator('[aria-label$="数据与评论筛选"]').get_by_role('button').filter(has_text=metric['label']).click()
            await full_comment(radar.get_by_role('region'))
            await radar.get_by_role('button', name='收起评论').click()
        if report.get('context_timeline'):
            insight = next(n for n in report['context_timeline'] if n['kind'] == 'insight')
            button = page.get_by_role('button').filter(has_text=insight['title'])
            await button.click()
            assert await button.get_attribute('aria-expanded') == 'true'
            await page.get_by_text(insight['evidence'][0]['excerpt'], exact=True).last.wait_for()
        await topics.scroll_into_view_if_needed()
        await page.screenshot(path='/tmp/eventlens-opinion-desktop.png')
        # Drill-down failure and retry use the same real API after a single injected failure.
        async def failure(route): await route.fulfill(status=503, json={'detail': 'TEST: comment read failure'})
        await page.route('**/chart-comments?**', failure)
        await topics.locator('[aria-label$="数据与评论筛选"]').get_by_role('button').first.click()
        await topics.get_by_role('alert').wait_for()
        await page.unroute('**/chart-comments?**', failure)
        await topics.get_by_role('button', name='重试', exact=True).click()
        await full_comment(topics.get_by_role('region'))
        await topics.get_by_role('button', name='收起评论').click()
        await page.set_viewport_size({'width': 390, 'height': 844})
        await topics.scroll_into_view_if_needed()
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Horizontal page overflow'
        bounds = await topics.bounding_box()
        assert bounds and bounds['width'] <= 390 and bounds['x'] >= 0, 'Chart outside mobile panel'
        await page.screenshot(path='/tmp/eventlens-opinion-mobile.png')
        # Theme tokens are inherited by the chart surface/text, with an explicit light palette.
        await page.evaluate('''() => { document.documentElement.dataset.theme = 'light';
          for (const [k,v] of Object.entries({'--color-surface':'#ffffff','--color-canvas':'#f6f7f9','--color-ink':'#152032','--color-muted':'#586575','--color-line':'#d9dfe7','--color-line-strong':'#aeb9c8','--color-hover':'#eef2f6','--color-raised':'#ffffff','--color-brand':'#256c9d'})) document.documentElement.style.setProperty(k,v); }''')
        await page.screenshot(path='/tmp/eventlens-opinion-light.png')
        theme = await topics.evaluate('(element) => ({background: getComputedStyle(element).backgroundColor, palette: getComputedStyle(element).getPropertyValue("--opinion-series-0")})')
        assert theme['background'] in {'rgb(255, 255, 255)', 'color(srgb 1 1 1)'}, theme
        await page.screenshot(path='/tmp/eventlens-opinion-light.png')
        assert not errors, errors
        print(json.dumps({'browser': 'passed', 'charts': [c['type'] for c in report['charts']],
            'sample_size': report['stats']['analyzed_count'], 'drilldown_requests': len(requests),
            'desktop_mobile_keyboard_tooltip_retry_theme': 'passed', 'new_agent_tasks': 0}))
        await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--base', default='http://127.0.0.1:3101'); parser.add_argument('--task', required=True)
    parser.add_argument('--api-base', help='Optional explicit TEST fixture server; never a production fallback')
    args = parser.parse_args();asyncio.run(run(args.base.rstrip('/'), args.task, args.api_base))
