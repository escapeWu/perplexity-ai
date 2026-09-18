"""Jobs API lifecycle and MCP handle adapters, sharing one execution owner."""
import asyncio
import importlib
import json

import pytest

from perplexity.server import jobs
from tests.conftest import request_for


def request(endpoint, job_id, *, query="", method="GET", token=True):
    return request_for(endpoint, method=method, query=query, params={"job_id": job_id}, token=token)


@pytest.mark.asyncio
async def test_one_submission_supports_stream_and_complete_result(api_runtime):
    response = await jobs.jobs(request_for('/v1/jobs', {"model": "perplexity-search", "messages": [{"role": "user", "content": "hello"}]}))
    assert response.status_code == 202
    accepted = json.loads(response.body)
    job_id = accepted['job_id']
    await asyncio.wait_for(api_runtime.test_upstream.started['hello'].wait(), 1)
    pending = await jobs.job_result(request('/v1/jobs/result', job_id, query='wait_seconds=0.01'))
    assert pending.status_code == 202 and pending.headers['retry-after'] == '1'
    stream = await jobs.job_events(request('/v1/jobs/events', job_id))
    first = await asyncio.wait_for(anext(stream.body_iterator), 1)
    assert 'event: snapshot' in first
    result = asyncio.create_task(jobs.job_result(request('/v1/jobs/result', job_id, query='wait_seconds=2')))
    api_runtime.test_upstream.release['hello'].set()
    events = [part async for part in stream.body_iterator]
    final = json.loads((await result).body)
    assert any('event: terminal' in part for part in events)
    assert final['state'] == 'completed'
    assert final['result']['answer'] == 'hello partial complete'
    assert len(api_runtime.test_upstream.calls) == 1
    assert not api_runtime.observers


@pytest.mark.asyncio
async def test_event_disconnect_preserves_job_and_explicit_cancel_is_idempotent(api_runtime):
    job = await api_runtime.submit(query='detached')
    await asyncio.wait_for(api_runtime.test_upstream.started['detached'].wait(), 1)
    response = await jobs.job_events(request('/events', job['id']))
    await anext(response.body_iterator)
    await response.body_iterator.aclose()
    assert (await api_runtime.get(job['id']))['state'] == 'running'
    await jobs.job_cancel(request('/cancel', job['id'], method='POST'))
    final = await api_runtime.wait(job['id'])
    assert final['state'] == 'cancelled'
    repeated = await jobs.job_cancel(request('/cancel', job['id'], method='POST'))
    assert json.loads(repeated.body)['state'] == 'cancelled'
    result = await jobs.job_result(request('/result', job['id']))
    assert result.status_code == 409
    assert api_runtime.sessions.get_messages(job['session_id']) == []


@pytest.mark.asyncio
async def test_job_routes_authenticate_before_lookup(api_runtime):
    for endpoint in [jobs.job_detail, jobs.job_result, jobs.job_events, jobs.job_cancel]:
        assert (await endpoint(request('/v1/jobs/private', 'private', token=False))).status_code == 401
    assert not api_runtime.test_upstream.calls


@pytest.mark.asyncio
async def test_foreign_event_cursor_and_nonfinite_wait_are_rejected(api_runtime):
    job = await api_runtime.submit(query='hello')
    cursor = await jobs.job_events(request('/events', job['id'], query='after=another-job:0'))
    assert cursor.status_code == 400
    result = await jobs.job_result(request('/result', job['id'], query='wait_seconds=nan'))
    assert result.status_code == 400


@pytest.mark.asyncio
async def test_retention_reconnect_uses_authoritative_snapshot(api_runtime):
    job = await api_runtime.submit(query='retained answer')
    api_runtime.test_upstream.release['retained answer'].set()
    final = await api_runtime.wait(job['id'])
    await api_runtime.db(lambda: expire_events(api_runtime, job['id']))
    response = await jobs.job_events(request('/events', job['id'], query='after=0'))
    events = [part async for part in response.body_iterator]
    assert len(events) == 2
    assert 'retained answer partial complete' in events[0]
    assert 'event: terminal' in events[1]
    assert final['state'] == 'completed'


def expire_events(runtime, job_id):
    with runtime.sessions._connect() as conn:
        conn.execute('DELETE FROM chat_job_events WHERE job_id=?', (job_id,))


@pytest.mark.asyncio
async def test_mcp_detached_status_wait_does_not_cancel(api_runtime):
    tools = importlib.import_module('perplexity.server.mcp')
    accepted = await tools.perplexity_task_submit.fn('mcp task')
    assert accepted['status'] == 'ok'
    status = await tools.perplexity_task_status.fn(accepted['id'], wait_seconds=0.01)
    assert status['state'] in ('queued', 'running')
    api_runtime.test_upstream.release['mcp task'].set()
    await api_runtime.wait(accepted['id'])
    complete = await tools.perplexity_task_status.fn(accepted['id'])
    assert complete['state'] == 'completed'
    assert complete['snapshot']['answer'] == 'mcp task partial complete'
    unchanged = await tools.perplexity_task_cancel.fn(accepted['id'])
    assert unchanged['state'] == 'completed'
    assert len(api_runtime.test_upstream.calls) == 1
