"""Isolated UI transport fixtures; no model calls or paid analysis.
Run against npm run dev. Requires an existing Python Playwright installation.
"""
import asyncio
import json
import os
from playwright.async_api import async_playwright, expect

BASE = os.getenv('EVENTLENS_TEST_URL', 'http://127.0.0.1:3000')

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={'width': 1280, 'height': 850}, reduced_motion='reduce')
        page = await ctx.new_page()
        clear_calls = []
        async def threads(route):
            if route.request.method == 'DELETE':
                clear_calls.append(route.request.url)
                if len(clear_calls) == 1:
                    return await route.fulfill(status=503, json={'detail': 'TEST 清空失败'})
                return await route.fulfill(json={'cleared': True, 'thread_id': 'a' * 32})
            await route.fulfill(json={'thread_id': 'a' * 32, 'messages': []})
        await page.route('**/api/copilot/threads*', threads)
        requests = []
        artifact = {'id': 'b' * 32, 'title': 'TEST 热点', 'kind': 'trace', 'status': 'completed', 'message': 'TEST', 'created_at': 1}
        trace = {'trace_id': 'TEST', 'selection': {}, 'selected_event': {'title': 'TEST 热点'}, 'subject': 'TEST 主题', 'status': 'partial',
                 'search_rounds': 1, 'search_queries': [], 'suggested_queries': [], 'timeline': [], 'sources': [], 'missing_aspects': ['TEST 资料不足'], 'warnings': []}
        await page.route('**/api/copilot/results/*', lambda r: r.fulfill(json={'artifact': artifact, 'result': trace, 'progress': []}))
        async def chat(route):
            body = route.request.post_data_json
            requests.append(body)
            if len(requests) == 1:
                return await route.fulfill(status=503, json={'detail': 'TEST 网络暂不可用'})
            if body['question'] == '停止测试':
                await asyncio.sleep(2)
                try:
                    await route.fulfill(body='data: '+json.dumps({'type': 'done', 'status': 'done'})+'\n\n', headers={'content-type': 'text/event-stream'})
                except Exception:
                    pass  # The test intentionally aborts this request.
                return
            frames = [{'type': 'delta', 'text': 'TEST 流式恢复成功'}, {'type': 'artifact', 'artifact': artifact}, {'type': 'done', 'status': 'done'}]
            await route.fulfill(body=''.join('data: '+json.dumps(e, ensure_ascii=False)+'\n\n' for e in frames), headers={'content-type': 'text/event-stream'})
        await page.route('**/api/copilot/chat', chat)
        await page.goto(BASE)
        assert await page.get_by_role('button', name='脉络重建', exact=True).count() == 0
        await page.get_by_role('textbox', name='输入 AI 问题').fill('重试测试')
        await page.get_by_role('button', name='发送消息').click()
        await expect(page.get_by_text('TEST 网络暂不可用', exact=True)).to_be_visible()
        await page.get_by_role('button', name='重试此问题').click()
        await expect(page.get_by_text('TEST 流式恢复成功', exact=True)).to_be_visible()
        assert requests[0]['user_id'] == requests[1]['user_id']
        await page.locator('.copilot-artifact').click()
        await expect(page.locator('.copilot-result h1')).to_have_text('TEST 热点')
        await expect(page.get_by_text('TEST 资料不足', exact=True)).to_be_visible()
        await page.locator('.copilot-result').get_by_role('button', name='返回热榜').click()
        await expect(page.locator('.ranking')).to_be_visible()
        await page.get_by_role('textbox', name='输入 AI 问题').fill('停止测试')
        await page.get_by_role('button', name='发送消息').click()
        await expect(page.get_by_role('button', name='清空聊天记录')).to_be_disabled()
        await page.get_by_role('button', name='停止生成').click()
        await expect(page.get_by_text('已停止回答。已启动的后台分析可在结果窗口单独查看或取消。')).to_be_visible()
        await page.get_by_role('button', name='收起 AI 侧栏').click()
        await page.get_by_role('button', name='百度', exact=True).click()
        await page.get_by_role('textbox', name='输入 AI 问题').fill('新榜单')
        await page.get_by_role('button', name='发送消息').click()
        await expect(page.get_by_role('button', name='停止生成')).to_have_count(0)
        assert requests[-1]['page']['platform_id'] == 'baidu'
        draft = page.get_by_role('textbox', name='输入 AI 问题')
        await draft.fill('TEST 保留草稿')
        count = await page.locator('.chat-message').count()
        page.once('dialog', lambda d: d.dismiss())
        await page.get_by_role('button', name='清空聊天记录').click()
        assert not clear_calls
        await expect(page.locator('.chat-message')).to_have_count(count)
        page.once('dialog', lambda d: d.accept())
        await page.get_by_role('button', name='清空聊天记录').click()
        await expect(page.get_by_text('TEST 清空失败', exact=True)).to_be_visible()
        await expect(page.locator('.chat-message')).to_have_count(count)
        page.once('dialog', lambda d: d.accept())
        await page.get_by_role('button', name='清空聊天记录').click()
        await expect(page.locator('.chat-message')).to_have_count(0)
        await expect(draft).to_have_value('TEST 保留草稿')
        await expect(page.get_by_role('button', name='清空聊天记录')).to_be_disabled()
        await expect(page.locator('.copilot-page-context').first).to_contain_text('百度')
        await page.reload()
        await page.get_by_role('button', name='对话', exact=True).click()
        await expect(page.locator('.chat-message')).to_have_count(0)
        await page.set_viewport_size({'width': 390, 'height': 844})
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await page.get_by_role('button', name='收起 AI 侧栏').click()
        await page.get_by_role('button', name='打开导航').click()
        await page.get_by_role('button', name='事件实验室', exact=True).click()
        await expect(page.get_by_text('实验选择', exact=True)).to_be_visible()
        print('PASS: clear confirmation/failure/success, preserved draft/page, reload, retry, stop, result view, mobile, laboratory')
        await browser.close()

asyncio.run(main())
