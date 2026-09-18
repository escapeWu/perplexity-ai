import asyncio
import json
from collections import defaultdict

import pytest

from perplexity.server import client_pool
from perplexity.server.files_store import FilesStore
from perplexity.server.job_runtime import JobRuntime
from perplexity.server.job_store import JobError
from perplexity.server.webui_sessions import WebUISessionStore, SessionBusy
from perplexity.upstream_protocol import UpstreamError


class FakeClient:
    own = True
    subscription_tier = "pro"
    authenticated = True
    def __init__(self, cookies):
        self.cookies = self._cookies = cookies
    def close(self):
        pass


class ControlledUpstream:
    def __init__(self):
        self.started = defaultdict(asyncio.Event)
        self.release = defaultdict(asyncio.Event)
        self.closed = defaultdict(asyncio.Event)
        self.calls = []
        self.in_flight = 0
        self.peak = 0

    async def __call__(self, client, **params):
        query = params["query"]
        self.calls.append(params)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        self.started[query].set()
        try:
            yield {"answer": query + " partial", "_follow_up": {"backend_uuid": "backend-" + query, "attachments": []}}
            await self.release[query].wait()
            if query == "empty response":
                raise UpstreamError("No answer", "empty_answer")
            yield {"answer": query + " partial complete", "status": "COMPLETED",
                   "_follow_up": {"backend_uuid": "backend-" + query, "attachments": []}}
        finally:
            self.in_flight -= 1
            self.closed[query].set()


@pytest.fixture
async def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(client_pool, "Client", FakeClient)
    config = tmp_path / "pool.json"
    config.write_text(json.dumps({"tokens": [{"id": "one-account", "csrf_token": "fake", "session_token": "fake"}],
        "concurrency": {"max_concurrency": 2, "global_max_running": 2, "start_rate": 100, "burst": 2},
        "timeouts": {"search": 1234}, "extension": {"keep": True}}))
    pool = client_pool.ClientPool(str(config))
    sessions = WebUISessionStore(tmp_path / "sessions.sqlite3")
    source = ControlledUpstream()
    runtime = JobRuntime(sessions, pool, transport=source, files=FilesStore(tmp_path / "uploads"))
    await runtime.start()
    try:
        yield runtime, source, pool, sessions
    finally:
        await runtime.close()


async def terminal(runtime, job):
    return await asyncio.wait_for(runtime.wait(job["id"]), 3)


@pytest.mark.asyncio
async def test_one_account_two_sessions_stream_and_full_share_execution(environment):
    runtime, source, pool, sessions = environment
    a = await runtime.submit(query="alpha question", idempotency_key="a")
    b = await runtime.submit(query="beta question")
    await asyncio.wait_for(asyncio.gather(source.started["alpha question"].wait(), source.started["beta question"].wait()), 2)
    assert source.peak == 2
    assert a["account_id"] == b["account_id"] == "one-account"
    observer = runtime.events(a["id"])
    first = await anext(observer)
    assert first["type"] == "snapshot"
    same = await runtime.submit(query="alpha question", idempotency_key="a")
    assert same["id"] == a["id"]
    with pytest.raises(JobError) as conflict:
        await runtime.submit(query="another question", session_id=a["session_id"])
    assert conflict.value.code == "session_busy"
    waiter = asyncio.create_task(runtime.wait(b["id"]))
    source.release["alpha question"].set()
    result_a = await terminal(runtime, a)
    assert not waiter.done()
    source.release["beta question"].set()
    result_b = await asyncio.wait_for(waiter, 2)
    await observer.aclose()
    assert result_a["state"] == result_b["state"] == "completed"
    assert len(source.calls) == 2
    assert [m["content"] for m in sessions.get_messages(a["session_id"])][-1] == "alpha question partial complete"
    assert [m["content"] for m in sessions.get_messages(b["session_id"])][-1] == "beta question partial complete"
    assert pool.clients["one-account"].in_flight == 0


@pytest.mark.asyncio
async def test_cancel_releases_slot_and_never_commits_late(environment):
    runtime, source, pool, sessions = environment
    pool.update_concurrency({"max_concurrency": 1})
    a = await runtime.submit(query="alpha question")
    b = await runtime.submit(query="beta question")
    await asyncio.wait_for(source.started["alpha question"].wait(), 2)
    assert not source.started["beta question"].is_set()
    assert (await runtime.get(b["id"]))["state"] == "queued"
    await runtime.cancel(a["id"])
    assert (await terminal(runtime, a))["state"] == "cancelled"
    await asyncio.wait_for(source.closed["alpha question"].wait(), 1)
    await asyncio.wait_for(source.started["beta question"].wait(), 1)
    source.release["alpha question"].set()
    assert sessions.get_messages(a["session_id"]) == []
    source.release["beta question"].set()
    assert (await terminal(runtime, b))["state"] == "completed"


@pytest.mark.asyncio
async def test_observer_disconnect_does_not_stop_detached_job(environment):
    runtime, source, _, sessions = environment
    job = await runtime.submit(query="detached question", detached=True)
    await asyncio.wait_for(source.started["detached question"].wait(), 2)
    observer = runtime.events(job["id"])
    await anext(observer)
    await observer.aclose()
    assert (await runtime.get(job["id"]))["state"] == "running"
    source.release["detached question"].set()
    assert (await terminal(runtime, job))["state"] == "completed"
    assert len(sessions.get_messages(job["session_id"])) == 2


@pytest.mark.asyncio
async def test_deadline_and_empty_result_are_not_success(environment):
    runtime, source, pool, sessions = environment
    pool.get_search_timeout = lambda _: 0.04
    job = await runtime.submit(query="timeout question")
    assert (await terminal(runtime, job))["state"] == "timed_out"
    assert sessions.get_messages(job["session_id"]) == []
    pool.get_search_timeout = lambda _: 5
    job = await runtime.submit(query="empty response")
    source.release["empty response"].set()
    result = await terminal(runtime, job)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "empty_answer"
    assert sessions.get_messages(job["session_id"]) == []
    assert pool.clients["one-account"].request_count == 0


@pytest.mark.asyncio
async def test_restart_preserves_queued_and_interrupts_running(environment):
    runtime, source, pool, sessions = environment
    pool.update_concurrency({"max_concurrency": 1})
    a = await runtime.submit(query="running question")
    b = await runtime.submit(query="queued question")
    await asyncio.wait_for(source.started["running question"].wait(), 2)
    await runtime.close()
    assert runtime.store.get(a["id"])["state"] == "interrupted"
    assert runtime.store.get(b["id"])["state"] == "queued"
    replacement = JobRuntime(sessions, pool, transport=source, files=runtime.files)
    await replacement.start()
    try:
        await asyncio.wait_for(source.started["queued question"].wait(), 2)
        source.release["queued question"].set()
        assert (await terminal(replacement, b))["state"] == "completed"
        assert len([p for p in source.calls if p["query"] == "running question"]) == 1
    finally:
        await replacement.close()


@pytest.mark.asyncio
async def test_active_session_delete_and_idempotency_conflict(environment):
    runtime, source, _, sessions = environment
    job = await runtime.submit(query="first question", idempotency_key="key")
    with pytest.raises(SessionBusy):
        await runtime.db(sessions.delete_session, job["session_id"])
    with pytest.raises(JobError) as error:
        await runtime.submit(query="changed question", idempotency_key="key")
    assert error.value.code == "idempotency_conflict"
    await runtime.cancel(job["id"])
    await terminal(runtime, job)
    await runtime.db(sessions.delete_session, job["session_id"])


@pytest.mark.asyncio
async def test_success_persists_complete_config(environment):
    runtime, source, pool, _ = environment
    job = await runtime.submit(query="saved config question")
    source.release["saved config question"].set()
    await terminal(runtime, job)
    if runtime.tasks:
        await asyncio.gather(*list(runtime.tasks.values()))
    config = json.loads(open(pool._config_path).read())
    assert config["timeouts"]["search"] == 1234
    assert config["concurrency"]["max_concurrency"] == 2
    assert config["extension"] == {"keep": True}
