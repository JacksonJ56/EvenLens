"""Small durable repository: PostgreSQL in deployments, SQLite for local development.

Only bounded JSON and minimized comments are stored. No browser cookies, usernames or keys.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, Text, create_engine, insert, select, update

metadata = MetaData()
tasks = Table("opinion_tasks", metadata, Column("id", String(80), primary_key=True),
              Column("idempotency", String(80), unique=True, nullable=False), Column("status", String(30)),
              Column("stage", String(50)), Column("message", Text), Column("payload", JSON),
              Column("checkpoint", JSON), Column("usage", JSON), Column("created_at", String(40)),
              Column("updated_at", String(40)))
datasets = Table("opinion_datasets", metadata, Column("id", String(80), primary_key=True),
                 Column("binding", JSON), Column("posts", JSON), Column("stats", JSON))
comments = Table("opinion_comments", metadata, Column("dataset_id", String(80), primary_key=True),
                 Column("ordinal", Integer, primary_key=True), Column("post_id", String(120)),
                 Column("comment_id", String(120)), Column("content", Text), Column("body", JSON))
cache = Table("opinion_analysis_cache", metadata, Column("key", String(64), primary_key=True), Column("body", JSON))
reports = Table("opinion_reports", metadata, Column("task_id", String(80), primary_key=True), Column("body", JSON))
events = Table("opinion_task_events", metadata, Column("task_id", String(80), primary_key=True),
               Column("ordinal", Integer, primary_key=True), Column("stage", String(50)),
               Column("message", Text), Column("at", String(40)))
external_sources = Table("opinion_external_sources", metadata, Column("task_id", String(80), primary_key=True),
                         Column("id", String(80), primary_key=True), Column("body", JSON))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def binding(payload) -> dict:
    return {"category_id": payload.selection.category_id, "platform_id": payload.selection.platform_id,
            "feed_id": payload.selection.feed_id, "event_id": payload.event.id}


class OpinionStore:
    def __init__(self, url: str):
        self.engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
                                    pool_pre_ping=True)
        metadata.create_all(self.engine)

    def get_task(self, task_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(tasks).where(tasks.c.id == task_id)).mappings().first()
            return dict(row) if row else None

    def create_task(self, payload) -> tuple[dict, bool]:
        from sqlalchemy.exc import IntegrityError
        with self.engine.connect() as db:
            previous = db.execute(select(tasks).where(tasks.c.idempotency == payload.idempotency_key)).mappings().first()
        if previous:
            return dict(previous), False
        task = dict(id=uuid4().hex, idempotency=payload.idempotency_key, status="queued", stage="queued",
                    message="任务已排队", payload=payload.model_dump(mode="json"), checkpoint={}, usage={},
                    created_at=now(), updated_at=now())
        try:
            with self.engine.begin() as db:
                db.execute(insert(tasks).values(**task))
        except IntegrityError:
            return self.create_task(payload)
        return task, True

    def update_task(self, task_id: str, **fields):
        with self.engine.begin() as db:
            db.execute(update(tasks).where(tasks.c.id == task_id).values(**fields, updated_at=now()))

    def task_events(self, task_id):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(select(events.c.stage, events.c.message, events.c.at)
                    .where(events.c.task_id == task_id).order_by(events.c.ordinal)).mappings()]

    def record_event(self, task_id, stage, message):
        previous = self.task_events(task_id)
        if previous and previous[-1]["stage"] == stage:
            return
        # One event loop/process owns each task; no competing ordinal allocator.
        with self.engine.begin() as db:
            db.execute(insert(events).values(task_id=task_id, ordinal=len(previous), stage=stage, message=message, at=now()))

    def interrupt_running(self):
        with self.engine.begin() as db:
            db.execute(update(tasks).where(tasks.c.status.in_(["running", "queued"])).values(
                status="interrupted", message="服务已重启，可从已保存的数据阶段恢复", updated_at=now()))

    def save_dataset(self, payload, posts, prepared, stats, dataset_id: str | None = None):
        dataset_id = dataset_id or uuid4().hex
        with self.engine.begin() as db:
            db.execute(insert(datasets).values(id=dataset_id, binding=binding(payload), posts=[p.model_dump(mode="json") for p in posts], stats=stats.model_dump()))
            if prepared:
                db.execute(insert(comments), [dict(dataset_id=dataset_id, ordinal=i, post_id=c.post_id,
                           comment_id=c.comment_id, content=c.content, body=c.model_dump(mode="json"))
                           for i, c in enumerate(prepared)])
        return dataset_id

    def dataset(self, dataset_id: str):
        with self.engine.connect() as db:
            row = db.execute(select(datasets).where(datasets.c.id == dataset_id)).mappings().first()
            return dict(row) if row else None

    def read_comments(self, dataset_id: str, *, post_id: str | None = None, keyword: str | None = None,
                      ids: list[str] | None = None, limit: int = 1200, offset: int = 0):
        query = select(comments.c.body).where(comments.c.dataset_id == dataset_id)
        if post_id:
            query = query.where(comments.c.post_id == post_id)
        if keyword:
            query = query.where(comments.c.content.contains(keyword, autoescape=True))
        if ids is not None:
            query = query.where(comments.c.comment_id.in_(ids))
        with self.engine.connect() as db:
            return list(db.execute(query.order_by(comments.c.ordinal).offset(offset).limit(limit)).scalars())

    def cache_get(self, key):
        with self.engine.connect() as db:
            return db.execute(select(cache.c.body).where(cache.c.key == key)).scalar_one_or_none()

    def cache_put(self, key, body):
        from sqlalchemy.exc import IntegrityError
        try:
            with self.engine.begin() as db:
                db.execute(insert(cache).values(key=key, body=body))
        except IntegrityError:
            pass

    def save_report(self, task_id, body):
        with self.engine.begin() as db:
            db.execute(reports.delete().where(reports.c.task_id == task_id))
            db.execute(insert(reports).values(task_id=task_id, body=body))

    def save_sources(self, task_id, sources):
        with self.engine.begin() as db:
            db.execute(external_sources.delete().where(external_sources.c.task_id == task_id))
            if sources:
                db.execute(insert(external_sources), [{"task_id": task_id, "id": sid, "body": body} for sid, body in sources.items()])

    def source(self, task_id, source_id):
        with self.engine.connect() as db:
            return db.execute(select(external_sources.c.body).where(
                external_sources.c.task_id == task_id, external_sources.c.id == source_id)).scalar_one_or_none()

    def report(self, task_id):
        with self.engine.connect() as db:
            return db.execute(select(reports.c.body).where(reports.c.task_id == task_id)).scalar_one_or_none()

    def historical(self, title: str):
        with self.engine.connect() as db:
            rows = db.execute(select(tasks.c.id, tasks.c.payload).where(tasks.c.status.in_(["completed", "partial"]))
                              .order_by(tasks.c.created_at.desc()).limit(100)).all()
        terms = set(title.split())
        return [{"task_id": row.id, "event": row.payload["event"]} for row in rows
                if terms.intersection(row.payload["event"]["title"].split())][:5]
