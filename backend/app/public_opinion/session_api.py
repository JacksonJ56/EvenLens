from fastapi import APIRouter, Request
from .sessions import local_action

router = APIRouter(prefix='/api/public-opinion/sessions', tags=['platform-sessions'])


@router.get('/{platform}')
async def session_status(platform: str, request: Request):
    return request.app.state.opinion_sessions.status(platform)


@router.post('/{platform}/check', status_code=202)
async def check_session(platform: str, request: Request):
    local_action(request)
    return await request.app.state.opinion_sessions.start(platform, 'check')


@router.post('/{platform}/login', status_code=202)
async def login_session(platform: str, request: Request):
    local_action(request)
    return await request.app.state.opinion_sessions.start(platform, 'login')


@router.post('/{platform}/confirm', status_code=202)
async def confirm_session(platform: str, request: Request):
    local_action(request)
    return request.app.state.opinion_sessions.confirm(platform)


@router.delete('/{platform}')
async def cancel_session(platform: str, request: Request):
    local_action(request)
    return await request.app.state.opinion_sessions.cancel(platform)
