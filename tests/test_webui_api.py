"""WebUI compatibility routes, session CRUD and pagination over durable jobs."""
import asyncio
import json

import pytest

from perplexity.server import webui
from tests.conftest import request_for


@pytest.mark.asyncio
async def test_session_crud_and_authentication(api_runtime):
    assert (await webui.webui_sessions(request_for('/v1/webui/sessions', token=False))).status_code == 401
    response = await webui.webui_sessions(request_for('/v1/webui/sessions', {'title': 'Native thread'}))
    assert response.status_code == 201
    session = json.loads(response.body)
    params = {'session_id': session['id']}
    detail = await webui.webui_session_detail(request_for('/v1/webui/sessions/x', method='GET', params=params))
    assert json.loads(detail.body)['messages'] == []
    renamed = await webui.webui_session_detail(request_for('/v1/webui/sessions/x', {'title': 'Renamed'}, method='PATCH', params=params))
    assert json.loads(renamed.body)['title'] == 'Renamed'
    listing = await webui.webui_sessions(request_for('/v1/webui/sessions', method='GET'))
    assert json.loads(listing.body)['data'][0]['id'] == session['id']
    deleted = await webui.webui_session_detail(request_for('/v1/webui/sessions/x', method='DELETE', params=params))
    assert json.loads(deleted.body) == {'id': session['id'], 'deleted': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
async def test_current_turn_binding_commits_and_native_follow_up(api_runtime, stream):
    session = api_runtime.sessions.create_session()
    source = api_runtime.test_upstream
    for text in ['first', 'second']:
        source.release[text].set()
        response = await webui.webui_chat_completions(request_for('/v1/webui/chat/completions', {
            'session_id': session.id, 'model': 'gpt-5-6-terra', 'thinking': True,
            'messages': [{'role': 'user', 'content': text}], 'stream': stream}))
        assert response.status_code == 200
        if stream:
            data = [item async for item in response.body_iterator]
            result = json.loads(data[-2][6:])
            assert data[-1] == 'data: [DONE]\n\n'
        else:
            result = json.loads(response.body)
        assert result['webui_session']['id'] == session.id
        assert result['model'] == 'gpt-5-6-terra-thinking'
    assert source.calls[-1]['query'] == 'second'
    assert source.calls[-1]['follow_up']['backend_uuid'] == 'backend-first'
    assert api_runtime.sessions.get_session(session.id).client_id == 'one-account'
    assert len(api_runtime.sessions.get_messages(session.id)) == 4


@pytest.mark.asyncio
async def test_failure_keeps_binding_but_never_commits_empty_turn(api_runtime):
    session = api_runtime.sessions.create_session()
    async def no_cursor(client, **params):
        yield {'answer': 'draft', 'status': 'COMPLETED'}
    api_runtime.transport = no_cursor
    response = await webui.webui_chat_completions(request_for('/v1/webui/chat/completions', {
        'session_id': session.id, 'model': 'perplexity-search', 'messages': [{'role': 'user', 'content': 'hello'}], 'stream': False}))
    assert response.status_code == 502
    assert api_runtime.sessions.get_session(session.id).client_id == 'one-account'
    assert api_runtime.sessions.get_messages(session.id) == []
    assert json.loads(response.body)['error']['type'] == 'upstream_incomplete'


@pytest.mark.asyncio
async def test_busy_session_returns_conflict_without_blocking_other_session(api_runtime):
    job = await api_runtime.submit(query='running')
    response = await webui.webui_chat_completions(request_for('/v1/webui/chat/completions', {
        'session_id': job['session_id'], 'model': 'perplexity-search', 'messages': [{'role': 'user', 'content': 'duplicate'}]}))
    assert response.status_code == 409
    assert json.loads(response.body)['error']['active_job_id'] == job['id']
    deletion = await webui.webui_session_detail(request_for('/v1/webui/sessions/x', method='DELETE', params={'session_id': job['session_id']}))
    assert deletion.status_code == 409
    other = await api_runtime.submit(query='other session')
    await asyncio.wait_for(api_runtime.test_upstream.started['other session'].wait(), 1)
    assert other['session_id'] != job['session_id']


@pytest.mark.asyncio
async def test_sessions_paginate_when_timestamps_match(api_runtime):
    sessions = [api_runtime.sessions.create_session(str(index)) for index in range(4)]
    with api_runtime.sessions._connect() as conn:
        conn.execute('UPDATE webui_sessions SET updated_at=1')
    first = json.loads((await webui.webui_sessions(request_for('/v1/webui/sessions', method='GET', query='limit=2'))).body)
    second = json.loads((await webui.webui_sessions(request_for('/v1/webui/sessions', method='GET', query='limit=2&before=' + first['next_cursor']))).body)
    assert {item['id'] for item in first['data'] + second['data']} == {s.id for s in sessions}
    assert second['has_more'] is False
