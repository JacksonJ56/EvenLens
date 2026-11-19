"""Run using the independent crawler interpreter, never emit raw errors or tokens."""
import asyncio
import json
import logging
import os
from pathlib import Path
import sys


def minimize_note(note, expected_id):
    if not isinstance(note, dict) or note.get('note_id') != expected_id:
        return {'status': 'identity_mismatch'}
    title, content = note.get('title'), note.get('desc')
    if not isinstance(content, str) or not content.strip():
        return {'status': 'no_text'}
    return {'status': 'ok', 'post_id': expected_id, 'title': title[:500] if isinstance(title, str) else '',
            'content': content[:5000], 'published_at': note.get('time') if isinstance(note.get('time'), (str, int, float)) else None}


async def read():
    sys.path.insert(0, os.getcwd())
    logging.disable(logging.CRITICAL)
    from xhs_context import xhs_client
    async with xhs_client(os.environ['MEDIACRAWLER_COOKIES_XHS'], os.environ['EVENTLENS_POST_URL']) as (client, info):
        note = await client.get_note_by_id(info.note_id, info.xsec_source, info.xsec_token)
        return minimize_note(note, info.note_id)


if __name__ == '__main__':
    try:
        body = asyncio.run(read())
    except Exception as error:
        # Never retry or switch identities after an access-control response.
        kind = type(error).__name__
        body = {'status': 'restricted' if kind in {'IPBlockError', 'PlatformAccessError'} else
                'not_found' if kind == 'NoteNotFoundError' else 'failed'}
    output = Path(os.environ['EVENTLENS_POST_OUTPUT'])
    output.write_text(json.dumps(body, ensure_ascii=False))
    output.chmod(0o600)
