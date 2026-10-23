from contextlib import closing
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
import pymysql
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
log_dir = ROOT / "logs"
log_dir.mkdir(exist_ok=True)
logger = logging.getLogger("apiele")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

app = FastAPI(title="APIELE-TEST 数据库测试", docs_url=None, redoc_url=None)


def connect():
    password = os.getenv("DB_PASSWORD", "")
    if not password:
        raise ValueError("DB_PASSWORD is required")
    port = int(os.getenv("DB_PORT", "13307"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid DB_PORT")
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"), port=port,
        user=os.getenv("DB_USER", "apiele_dev"), password=password,
        database=os.getenv("DB_NAME", "apiele_test_dev"), charset="utf8mb4",
        cursorclass=DictCursor, connect_timeout=5, read_timeout=10,
        write_timeout=10, autocommit=True,
    )


def ensure_table(cursor):
    cursor.execute("""CREATE TABLE IF NOT EXISTS apiele_test_notes (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        content VARCHAR(500) NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    return response


def failure(request: Request, exc: Exception):
    error_id = request.state.request_id
    code = exc.args[0] if isinstance(exc, pymysql.MySQLError) and exc.args else None
    # Avoid raw exceptions/SQL parameters: these can contain passwords or record text.
    logger.error("request_id=%s method=%s path=%s type=%s mysql_code=%s",
                 error_id, request.method, request.url.path, type(exc).__name__, code)
    if isinstance(exc, ValueError):
        message = "数据库配置不完整或端口格式错误，请检查 .env 并重启服务。"
    else:
        message = {
            1045: "数据库账号或密码不正确，请检查 .env 后重启服务。",
            1049: "数据库不存在，请检查 DB_NAME。",
            1044: "当前数据库账号没有访问该数据库的权限。",
            1142: "数据库账号缺少操作测试表的权限。",
            2003: "连接不到数据库，请检查 SSH 隧道是否已启动，以及端口是否正确。",
            2013: "数据库连接中断或响应超时，请检查隧道和数据库状态。",
        }.get(code, "数据库操作失败，请检查服务器数据库状态，并提供异常编号。")
    return JSONResponse(status_code=503, content={"detail": message, "error_id": error_id})


app.add_exception_handler(pymysql.MySQLError, failure)
app.add_exception_handler(ValueError, failure)


class NoteInput(BaseModel):
    content: str = Field(min_length=1, max_length=500)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "app" / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/database")
def database():
    with closing(connect()) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT VERSION() AS version, DATABASE() AS database_name")
        info = cursor.fetchone()
    return {"status": "connected", **info}


def serialize_note(row):
    return {**row, "created_at": row["created_at"].isoformat(sep=" ")
            if isinstance(row["created_at"], datetime) else row["created_at"]}


@app.get("/api/notes")
def list_notes():
    with closing(connect()) as connection, connection.cursor() as cursor:
        ensure_table(cursor)
        cursor.execute("SELECT id, content, created_at FROM apiele_test_notes ORDER BY id DESC LIMIT 50")
        rows = cursor.fetchall()
    return {"items": [serialize_note(row) for row in rows]}


@app.post("/api/notes", status_code=201)
def add_note(note: NoteInput):
    with closing(connect()) as connection, connection.cursor() as cursor:
        ensure_table(cursor)
        cursor.execute("INSERT INTO apiele_test_notes (content) VALUES (%s)", (note.content,))
        note_id = cursor.lastrowid
        cursor.execute("SELECT id, content, created_at FROM apiele_test_notes WHERE id = %s", (note_id,))
        row = cursor.fetchone()
    return serialize_note(row)
