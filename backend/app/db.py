"""数据库引擎与会话（SQLite）。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明基类。"""


def _build_engine():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{config.DB_PATH}",
        connect_args={"check_same_thread": False},   # FastAPI 多线程
        pool_pre_ping=True,
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    """FastAPI 依赖：请求级会话。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表（幂等）+ 轻量迁移。"""
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate() -> None:
    """给已有库补新增列（create_all 只建表，不会修改已存在的表）。

    已部署的 app.db 里 users 表没有 workshop 列，这里按需补上；
    历史行取默认空串（= 不限定车间）。
    """
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")}
        if "workshop" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN workshop VARCHAR(32) NOT NULL DEFAULT ''"
            )
