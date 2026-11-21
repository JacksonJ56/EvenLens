import time
from uuid import uuid4
from sqlalchemy import (
    JSON,
    Column,
    Float,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
    update,
    or_,
)

metadata = MetaData()
threads = Table(
    "copilot_threads",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("owner", String(64), nullable=False),
    Column("state", JSON, nullable=False),
    Column("lease", String(80)),
    Column("lease_until", Float, default=0),
)
jobs = Table(
    "copilot_jobs",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("owner", String(64), nullable=False),
    Column("fingerprint", String(64)),
    Column("kind", String(30)),
    Column("status", String(30)),
    Column("message", Text),
    Column("payload", JSON),
    Column("result", JSON),
    Column("task_id", String(80)),
    Column("created", Float),
)


class CopilotStore:
    def __init__(self, engine):
        self.engine = engine
        metadata.create_all(engine)
        with engine.begin() as db:
            db.execute(
                update(jobs)
                .where(jobs.c.kind == "trace", jobs.c.status.in_(["queued", "running"]))
                .values(status="interrupted", message="后端已重启，请重新发起分析")
            )

    def thread(self, identifier, owner):
        with self.engine.connect() as db:
            r = (
                db.execute(
                    select(threads).where(
                        threads.c.id == identifier, threads.c.owner == owner
                    )
                )
                .mappings()
                .first()
            )
            return dict(r) if r else None

    def create_thread(self, owner):
        identifier = uuid4().hex
        with self.engine.begin() as db:
            db.execute(
                insert(threads).values(
                    id=identifier,
                    owner=owner,
                    state={
                        "history": [],
                        "messages": [],
                        "events": {},
                        "artifacts": [],
                        "active_event": None,
                    },
                    lease_until=0,
                )
            )
        return self.thread(identifier, owner)

    def acquire(self, identifier, owner, request_id):
        with self.engine.begin() as db:
            r = db.execute(
                update(threads)
                .where(
                    threads.c.id == identifier,
                    threads.c.owner == owner,
                    or_(
                        threads.c.lease_until < time.time(),
                        threads.c.lease_until.is_(None),
                    ),
                )
                .values(lease=request_id, lease_until=time.time() + 180)
            )
        return r.rowcount == 1

    def save(self, identifier, owner, state):
        with self.engine.begin() as db:
            db.execute(
                update(threads)
                .where(threads.c.id == identifier, threads.c.owner == owner)
                .values(state=state)
            )

    def finish(self, identifier, owner, request_id, history, messages):
        row = self.thread(identifier, owner)
        if not row or row["lease"] != request_id:
            return False
        state = {**row["state"], "history": history, "messages": messages[-80:]}
        with self.engine.begin() as db:
            r = db.execute(
                update(threads)
                .where(
                    threads.c.id == identifier,
                    threads.c.owner == owner,
                    threads.c.lease == request_id,
                )
                .values(state=state, lease=None, lease_until=0)
            )
        return r.rowcount == 1

    def clear_history(self, identifier, owner):
        row = self.thread(identifier, owner)
        if not row:
            return False
        state = {
            **row["state"],
            "history": [],
            "messages": [],
            "events": {},
            "active_event": None,
        }
        # Keep completed reports/background jobs; invalidate any expired turn so
        # a late finish cannot put cleared messages back into this conversation.
        with self.engine.begin() as db:
            result = db.execute(
                update(threads)
                .where(
                    threads.c.id == identifier,
                    threads.c.owner == owner,
                    or_(
                        threads.c.lease_until < time.time(),
                        threads.c.lease_until.is_(None),
                    ),
                )
                .values(state=state, lease=None, lease_until=0)
            )
        return result.rowcount == 1

    def job(self, identifier, owner):
        with self.engine.connect() as db:
            r = (
                db.execute(
                    select(jobs).where(jobs.c.id == identifier, jobs.c.owner == owner)
                )
                .mappings()
                .first()
            )
            return dict(r) if r else None

    def recent(self, fingerprint, owner):
        with self.engine.connect() as db:
            r = (
                db.execute(
                    select(jobs)
                    .where(
                        jobs.c.fingerprint == fingerprint,
                        jobs.c.owner == owner,
                        jobs.c.created > time.time() - 21600,
                    )
                    .order_by(jobs.c.created.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            return dict(r) if r else None

    def new_job(self, owner, fingerprint, kind, payload):
        row = dict(
            id=uuid4().hex,
            owner=owner,
            fingerprint=fingerprint,
            kind=kind,
            payload=payload,
            status="queued",
            message="分析任务已排队",
            result=None,
            task_id=None,
            created=time.time(),
        )
        with self.engine.begin() as db:
            db.execute(insert(jobs).values(**row))
        return row

    def update_job(self, identifier, **values):
        with self.engine.begin() as db:
            db.execute(update(jobs).where(jobs.c.id == identifier).values(**values))
