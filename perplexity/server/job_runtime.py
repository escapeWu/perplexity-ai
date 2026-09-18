"""Single-owner asynchronous jobs, account admission and native conversation lifecycle."""
from __future__ import annotations

import asyncio
import sqlite3
import hashlib
import anyio
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress

from ..model_registry import get_model_registry
from ..upstream_async import search_stream
from ..upstream_protocol import UpstreamError, clean_result
from ..logger import get_logger
from .files_store import get_files_store
from .job_store import ACTIVE, TERMINAL, AsyncJobStore, JobError, JobStore, public_job
from .webui_sessions import sanitize_message_content, validate_session_id
from .utils import sanitize_query
from .progress import ProgressTracker

logger = get_logger("server.jobs")


class JobRuntime:
    """One runtime owns all routes' execution; observers never own detached jobs."""

    def __init__(self, sessions, pool, *, transport=search_stream, files=None, exclusive=True):
        self.sessions, self.pool = sessions, pool
        self.transport = transport
        self.files = files or get_files_store()
        self.exclusive = exclusive
        self.pending = {}
        self.tasks = {}
        self.cancel_requested = set()
        self.cleanup_tasks = set()
        self.persistences = set()
        self.admissions = set()
        self.observers = Counter()
        self.admission = asyncio.Lock()
        self.condition = asyncio.Condition()
        self.versions = Counter()
        self.wakeup = asyncio.Event()
        self.metrics = Counter()
        self.file_slots = asyncio.Semaphore(2)
        self.file_jobs = set()
        self.file_reads = set()
        self.file_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="job-file")
        self.storage_healthy = True
        self.accepting = False
        self.closing = False
        self.pool._event_loop = asyncio.get_running_loop()
        self.repository = None
        self.dispatcher = None
        self.lock_file = None

    async def start(self):
        if self.exclusive:
            import fcntl
            path = self.sessions.database_path.with_suffix(".runtime.lock")
            self.lock_file = path.open("a+")
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self.lock_file.close(); self.lock_file = None
                raise RuntimeError("This session database already has a task runner; use one server worker") from exc
        try:
            self.store = await asyncio.to_thread(JobStore, self.sessions)
            self.repository = AsyncJobStore(self.store)
            restored = await self.db(self.store.recover)
            for job in restored:
                if job["account_id"] not in self.pool.clients:
                    await self.db(self.store.finish, job["id"], "failed", {"code": "account_unavailable", "message": "Bound account is unavailable"})
                    continue
                self.pending[job["id"]] = job
                self.pool.adjust_queued(job["account_id"], 1)
                self.files.pin(job["payload"].get("file_ids", {}), job["id"])
            self.accepting = True
            self.dispatcher = asyncio.create_task(self._dispatch(), name="chat-dispatcher")
            return self
        except BaseException:
            if self.repository:
                await self.repository.close()
            if self.lock_file:
                self.lock_file.close(); self.lock_file = None
            raise

    async def db(self, method, *args, **kwargs):
        try:
            result = await self.repository.call(method, *args, **kwargs)
        except sqlite3.Error:
            self.storage_healthy = False
            self.metrics["storage_errors"] += 1
            raise
        if method == self.store.ping:
            self.storage_healthy = bool(result)
        return result

    async def _notify(self, job_id):
        async with self.condition:
            if job_id in self.pending or job_id in self.tasks or self.observers[job_id]:
                self.versions[job_id] += 1
            else:
                self.versions.pop(job_id, None)
            self.condition.notify_all()
        self.wakeup.set()

    async def submit(self, *, detached=False, **kwargs):
        if len(self.admissions) >= self.pool.get_concurrency_config()["global_max_queued"]:
            raise JobError("Task admission queue is full", "queue_full", 429)
        operation = asyncio.create_task(self._submit(**kwargs))
        self.admissions.add(operation)
        operation.add_done_callback(self.admissions.discard)
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                try:
                    job = await asyncio.shield(operation)
                    if not detached:
                        await self.cancel(job["id"], kwargs.get("principal", "default"))
                except Exception:
                    pass
            raise

    async def _submit(self, *, query, mode="auto", model=None, model_id="auto", session_id=None,
                     user_content=None, files=None, search_sources=None, language="en-US",
                     incognito=False, origin="webui", idempotency_key=None, principal="default"):
        query = sanitize_query(query)
        if session_id is not None:
            validate_session_id(session_id)
        if search_sources is not None and (not isinstance(search_sources, list) or not search_sources or any(source not in ("web", "scholar", "social") for source in search_sources)):
            raise ValueError("Invalid search sources")
        if not isinstance(language, str) or not language or any(char in language for char in "\r\n\x00"):
            raise ValueError("Invalid search language")
        definition = get_model_registry().resolve(mode, model)
        if model_id == "auto":
            model_id = definition.oai_id
        normalized_files = {name: data.encode() if isinstance(data, str) else data for name, data in (files or {}).items()}
        payload = {"query": query, "mode": mode, "model": model, "model_id": model_id,
                   "user_content": sanitize_message_content(query if user_content is None else user_content),
                   "search_sources": search_sources or ["web"], "language": language,
                   "incognito": bool(incognito or self.pool.is_incognito_enabled()),
                   "file_hashes": {name: hashlib.sha256(data).hexdigest() for name, data in normalized_files.items()}}
        async with self.admission:
            if not self.accepting or self.dispatcher is None or self.dispatcher.done():
                raise JobError("Task runner is not accepting work", "service_unavailable", 503)
            existing = await self.db(self.store.find_request, session_id, payload, idempotency_key, principal)
            if existing:
                return existing
            limits = self.pool.get_concurrency_config()
            if len(self.pending) >= limits["global_max_queued"]:
                raise JobError("Task queue is full", "queue_full", 429)
            session = await self.db(self.sessions.get_session, session_id) if session_id else None
            try:
                account = self.pool.select_for_job(get_model_registry().required_tier(mode, model), mode,
                    session.client_id if session else None, enqueue=True)
            except OverflowError as exc:
                raise JobError("Account queue is full", "queue_full", 429) from exc
            if account is None:
                raise JobError("No compatible account is available", "account_unavailable", 503)
            refs = {}
            created = registered = False
            try:
                refs = await asyncio.to_thread(self.files.stage, normalized_files) if normalized_files else {}
                payload["file_ids"] = refs
                job, created = await self.db(self.store.create, session_id, payload, origin=origin,
                    key=idempotency_key, principal=principal, account_id=account)
                if not created:
                    return job
                self.files.pin(refs, job["id"])
                self.pending[job["id"]] = job
                registered = True
                self.metrics["submitted"] += 1
                self.wakeup.set()
                return job
            finally:
                if not registered:
                    self.pool.adjust_queued(account, -1)
                if not created:
                    for file_id in refs.values():
                        await asyncio.to_thread(self.files.delete, file_id)

    async def _dispatch(self):
        last_prune = time.monotonic()
        while not self.closing:
            self.wakeup.clear()
            for job_id, job in list(self.pending.items()):
                if job_id not in self.pending:
                    continue
                limits = self.pool.get_concurrency_config(job["account_id"])
                if time.time() - job["created_at"] > limits["queue_timeout"]:
                    self._dequeue(job)
                    await self.db(self.store.finish, job_id, "timed_out", {"code": "queue_timeout", "message": "Task exceeded its queue deadline"})
                    self.files.unpin(job["payload"].get("file_ids", {}), job_id)
                    await self._notify(job_id)
                elif (job["account_id"] not in self.pool.clients or
                      not self.pool.clients[job["account_id"]].enabled or
                      self.pool.clients[job["account_id"]].state == "offline"):
                    self._dequeue(job)
                    await self.db(self.store.finish, job_id, "failed", {"code": "account_unavailable", "message": "Bound account is unavailable"})
                    self.files.unpin(job["payload"].get("file_ids", {}), job_id)
                    await self._notify(job_id)
                elif job["payload"].get("file_ids") and (len(self.file_jobs) >= 2 or len(self.file_reads) >= 2):
                    continue
                elif self.pool.try_acquire(job["account_id"], job["payload"]["mode"]):
                    if job["payload"].get("file_ids"):
                        self.file_jobs.add(job_id)
                    self._dequeue(job)
                    task = asyncio.create_task(self._run(job), name=job_id)
                    self.tasks[job_id] = task
                    task.add_done_callback(lambda task, job=job: self._task_done(task, job))
            if time.monotonic() - last_prune > 60:
                await self.db(self.store.prune_events)
                await asyncio.to_thread(self.files.prune)
                last_prune = time.monotonic()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.wakeup.wait(), 0.2)

    def _dequeue(self, job):
        if self.pending.pop(job["id"], None) is not None:
            self.pool.adjust_queued(job["account_id"], -1)

    def _task_done(self, task, job):
        self.pool.release(job["account_id"], job["payload"]["mode"])
        self.file_jobs.discard(job["id"])
        self.cancel_requested.discard(job["id"])
        self.tasks.pop(job["id"], None)
        if not self.observers.get(job["id"]):
            self.versions.pop(job["id"], None)
            self.observers.pop(job["id"], None)
        self.files.unpin(job["payload"].get("file_ids", {}), job["id"])
        self.wakeup.set()
        if task.cancelled() or task.exception() is not None:
            # Also covers cancellation before the coroutine's first instruction.
            cleanup = asyncio.create_task(self._settle_orphan(job))
            self.cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(self.cleanup_tasks.discard)

    async def _settle_orphan(self, job):
        try:
            await self.db(self.store.finish, job["id"], "interrupted" if self.closing else "cancelled")
            await self._notify(job["id"])
        except Exception:
            self.storage_healthy = False
            self.metrics["storage_errors"] += 1
            logger.error("Unable to settle task state; recovery required")

    async def _run(self, job):
        job_id, account = job["id"], job["account_id"]
        try:
            if not await self.db(self.store.start, job_id):
                return
            self.metrics["queue_seconds"] += time.time() - job["created_at"]
            await self._notify(job_id)
            timeout = self.pool.get_search_timeout(job["payload"]["mode"])
            await asyncio.wait_for(self._consume(job), timeout)
        except asyncio.CancelledError:
            await self.db(self.store.finish, job_id, "interrupted" if self.closing else "cancelled")
            self.metrics["cancelled"] += 1
        except asyncio.TimeoutError:
            await self.db(self.store.finish, job_id, "timed_out", {"code": "execution_timeout", "message": "Task exceeded its execution deadline"})
            self.metrics["timed_out"] += 1
        except (UpstreamError, JobError) as exc:
            self.pool.mark_job_error(account, exc.code, getattr(exc, "retry_after", 0))
            await self.db(self.store.finish, job_id, "failed", {"code": exc.code, "message": str(exc), "retry_after": getattr(exc, "retry_after", 0)})
            self.metrics[exc.code] += 1
        except Exception:
            await self.db(self.store.finish, job_id, "failed", {"code": "execution_error", "message": "Task execution failed"})
            self.metrics["execution_error"] += 1
            logger.error("Task %s failed during execution", job_id)
        finally:
            await self._notify(job_id)

    async def _consume(self, job):
        # Attachment-heavy tasks have an additional memory budget of two consumers.
        if job["payload"].get("file_ids"):
            async with self.file_slots:
                return await self._consume_stream(job)
        return await self._consume_stream(job)

    async def _consume_stream(self, job):
        payload, job_id = job["payload"], job["id"]
        session = await self.db(self.sessions.get_session, job["session_id"])
        client = self.pool.clients[job["account_id"]].client
        refs = payload.get("file_ids", {})
        files = {}
        if refs:
            read = asyncio.get_running_loop().run_in_executor(self.file_executor, self.files.load, refs)
            self.file_reads.add(read)
            read.add_done_callback(self._file_read_done)
            files = await asyncio.shield(read)
        upstream = self.transport(client, query=payload["query"], mode=payload["mode"],
            model=payload["model"], sources=payload["search_sources"], language=payload["language"],
            follow_up=session.follow_up(), incognito=payload["incognito"], files=files,
            timeout=self.pool.get_search_timeout(payload["mode"]),
            file_upload_timeout=self.pool.get_file_upload_timeout())
        previous, latest, last_publish = "", {}, 0.0
        progress_tracker, progress_states = ProgressTracker(), {}
        initial = progress_tracker.update({"text": [{"step_type": "INITIAL_QUERY"}]})
        for progress in initial:
            progress_states[progress["id"]] = progress
        await self.db(self.store.publish, job_id, "snapshot", {"answer": "", "progress": initial}, {"answer": "", "progress": initial})
        await self._notify(job_id)
        first_output = False
        started = time.monotonic()
        try:
            async for chunk in upstream:
                latest = chunk
                snapshot = clean_result(chunk)
                for progress in progress_tracker.update(chunk):
                    progress_states[progress["id"]] = progress
                snapshot["progress"] = list(progress_states.values())
                answer = snapshot.get("answer", "")
                if answer and not first_output:
                    first_output = True
                    self.metrics["ttft_seconds"] += time.monotonic() - started
                now = time.monotonic()
                if now - last_publish < 0.05 and chunk.get("status") != "COMPLETED":
                    continue
                if answer.startswith(previous):
                    kind, content = "delta", {"content": answer[len(previous):]}
                else:
                    kind, content = "snapshot", {"answer": answer}
                content["sources"] = snapshot.get("sources", [])
                content["progress"] = snapshot["progress"]
                await self.db(self.store.publish, job_id, kind, content, snapshot)
                previous, last_publish = answer, now
                await self._notify(job_id)
        finally:
            await upstream.aclose()
        result = clean_result(latest)
        completed_progress = progress_tracker.finish("completed")
        if completed_progress:
            progress_states[completed_progress["id"]] = completed_progress
        result["progress"] = list(progress_states.values())
        if not result.get("answer", "").strip():
            raise UpstreamError("Upstream completed without an answer", "empty_answer")
        cursor = latest.get("_follow_up")
        if not isinstance(cursor, dict) or not cursor.get("backend_uuid"):
            raise UpstreamError("Upstream response did not include a native cursor", "upstream_incomplete")
        committed = await self.db(self.store.complete, job_id, result, cursor)
        if committed:
            self.metrics["completed"] += 1
            self.metrics["execution_seconds"] += time.monotonic() - started
            persistence = asyncio.create_task(asyncio.to_thread(self.pool.mark_client_success, job["account_id"]))
            self.persistences.add(persistence)
            persistence.add_done_callback(self._persistence_done)
            with suppress(Exception):
                await asyncio.shield(persistence)
        else:
            await self.db(self.store.finish, job_id, "cancelled")

    def _file_read_done(self, future):
        self.file_reads.discard(future)
        if not future.cancelled():
            future.exception()
        self.wakeup.set()

    def _persistence_done(self, future):
        self.persistences.discard(future)
        if not future.cancelled() and future.exception() is not None:
            self.metrics["config_errors"] += 1
            logger.error("Task succeeded but account cookie persistence failed")

    async def get(self, job_id, principal="default"):
        return await self.db(self.store.get, job_id, principal)

    async def cancel(self, job_id, principal="default"):
        job = await self.db(self.store.cancel, job_id, principal)
        if job_id in self.pending:
            self._dequeue(self.pending[job_id])
            self.files.unpin(job["payload"].get("file_ids", {}), job_id)
        task = self.tasks.get(job_id)
        if job["state"] == "cancelling" and task and job_id not in self.cancel_requested:
            self.cancel_requested.add(job_id)
            task.cancel()
        await self._notify(job_id)
        return job

    async def events(self, job_id, *, after=0, principal="default", heartbeat=10):
        self.observers[job_id] += 1
        iterator = self._events(job_id, after=after, principal=principal, heartbeat=heartbeat)
        try:
            async for event in iterator:
                yield event
        finally:
            await iterator.aclose()
            self.observers[job_id] -= 1
            if not self.observers[job_id]:
                self.observers.pop(job_id, None)
                if job_id not in self.pending and job_id not in self.tasks:
                    self.versions.pop(job_id, None)

    async def _events(self, job_id, *, after=0, principal="default", heartbeat=10):
        job = await self.get(job_id, principal)
        if after < 0 or after > job["seq"]:
            raise JobError("Invalid event cursor", "invalid_cursor")
        seq = job["seq"]
        yield {"type": "snapshot", "seq": seq, "job": public_job(job, snapshot=True)}
        if job["state"] in TERMINAL:
            yield {"type": "terminal", "seq": seq, "job": public_job(job, snapshot=True)}
            return
        while not self.closing:
            version = self.versions[job_id]
            events = await self.db(self.store.events, job_id, seq)
            for event in events:
                seq = event["seq"]
                if event["type"] == "terminal":
                    event["job"] = public_job(await self.get(job_id, principal), snapshot=True)
                yield event
                if event["type"] == "terminal":
                    return
            if events:
                continue
            latest = await self.get(job_id, principal)
            if latest["state"] in TERMINAL:
                yield {"type": "terminal", "seq": latest["seq"], "job": public_job(latest, snapshot=True)}
                return
            try:
                async with self.condition:
                    await asyncio.wait_for(self.condition.wait_for(lambda: self.versions[job_id] != version or self.closing), heartbeat)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat", "seq": seq}

    async def wait(self, job_id, principal="default"):
        job = await self.get(job_id, principal)
        if job["state"] in TERMINAL:
            return job
        iterator = self.events(job_id, principal=principal)
        try:
            async for event in iterator:
                if event["type"] == "terminal":
                    return await self.get(job_id, principal)
        finally:
            await iterator.aclose()
        raise JobError("Task runner is closing", "service_unavailable", 503)

    def status(self):
        return {"ready": self.accepting and self.dispatcher is not None and not self.dispatcher.done() and self.storage_healthy,
                "storage_healthy": self.storage_healthy, "running_with_files": len(self.file_jobs),
                "running": len(self.tasks), "queued": len(self.pending), "metrics": dict(self.metrics),
                "limits": self.pool.get_concurrency_config()}

    async def close(self):
        self.accepting, self.closing = False, True
        self.wakeup.set()
        async with self.condition:
            self.condition.notify_all()
        if self.admissions:
            await asyncio.gather(*list(self.admissions), return_exceptions=True)
        if self.dispatcher:
            await asyncio.gather(self.dispatcher, return_exceptions=True)
        for job_id, task in list(self.tasks.items()):
            if job_id not in self.cancel_requested:
                self.cancel_requested.add(job_id)
                task.cancel()
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)
        if self.cleanup_tasks:
            await asyncio.gather(*list(self.cleanup_tasks), return_exceptions=True)
        for job in list(self.pending.values()):
            self._dequeue(job)
            self.files.unpin(job["payload"].get("file_ids", {}), job["id"])
        if self.file_reads:
            await asyncio.gather(*list(self.file_reads), return_exceptions=True)
        self.file_executor.shutdown(wait=False, cancel_futures=True)
        if self.persistences:
            await asyncio.gather(*list(self.persistences), return_exceptions=True)
        if self.repository:
            await self.repository.close()
        if self.lock_file:
            self.lock_file.close(); self.lock_file = None
