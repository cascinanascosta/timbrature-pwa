from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import base64
import hashlib
import io
import os
import secrets

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, select, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

try:
    import qrcode
except ImportError:
    qrcode = None

TZ = ZoneInfo("Europe/Rome")
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./timbrature.db"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="employee", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Punch(Base):
    __tablename__ = "punches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    qr_token_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class QRToken(Base):
    __tablename__ = "qr_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class EditLog(Base):
    __tablename__ = "edit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    punch_id: Mapped[int] = mapped_column(Integer, nullable=True)
    admin_id: Mapped[int] = mapped_column(Integer, nullable=True)
    old_ts: Mapped[str] = mapped_column(Text, nullable=True)
    new_ts: Mapped[str] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

Base.metadata.create_all(engine)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
        return secrets.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_seed_users():
    with Session(engine) as s:
        if s.scalar(select(User).where(User.username == "admin")) is None:
            s.add(User(name="Amministratore", username="admin", password_hash=hash_password("admin123"), role="admin"))
        if s.scalar(select(User).where(User.username == "demo")) is None:
            s.add(User(name="Dipendente Demo", username="demo", password_hash=hash_password("demo123"), role="employee"))
        s.commit()

ensure_seed_users()

app = FastAPI(title="Timbrature PWA", version="0.3-render")
SESSIONS: dict[str, dict] = {}

class Login(BaseModel):
    username: str
    password: str

class PunchRequest(BaseModel):
    token: str

class UserIn(BaseModel):
    name: str
    username: str
    password: str
    role: str = "employee"


def current(session: str) -> dict:
    user = SESSIONS.get(session)
    if not user:
        raise HTTPException(401, "Sessione non valida")
    return user

@app.get("/health")
def health():
    return {"ok": True, "time": now_utc().isoformat()}

@app.post("/api/login")
def login(req: Login):
    with Session(engine) as s:
        user = s.scalar(select(User).where(User.username == req.username, User.active.is_(True)))
        if user is None or not verify_password(req.password, user.password_hash):
            raise HTTPException(401, "Credenziali non valide")
        sid = secrets.token_urlsafe(32)
        SESSIONS[sid] = {"id": user.id, "name": user.name, "role": user.role}
        return {"session": sid, "name": user.name, "role": user.role}

@app.post("/api/qr")
def new_qr():
    token = secrets.token_urlsafe(32)
    created = now_utc()
    expires = created + timedelta(seconds=30)
    with Session(engine) as s:
        s.execute(delete(QRToken).where(QRToken.expires_at < created - timedelta(minutes=2)))
        s.add(QRToken(token_hash=token_hash(token), created_at=created, expires_at=expires, used=False))
        s.commit()

    image_data = None
    if qrcode is not None:
        qr = qrcode.QRCode(version=None, box_size=10, border=2)
        qr.add_data(token)
        qr.make(fit=True)
        img = qr.make_image()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_data = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return {"token": token, "expires_at": expires.isoformat(), "server_now": created.isoformat(), "image": image_data}

@app.get("/qr")
def qr_page():
    return FileResponse("backend/static/qr.html")

@app.post("/api/punch")
def punch(req: PunchRequest, session: str):
    user = current(session)
    if user["role"] != "employee":
        raise HTTPException(403, "Solo i dipendenti possono timbrare")
    now = now_utc()
    with Session(engine) as s:
        qr = s.get(QRToken, token_hash(req.token))
        if qr is None or qr.used:
            raise HTTPException(400, "QR non valido o già utilizzato")
        if qr.expires_at < now:
            raise HTTPException(400, "QR scaduto")
        last = s.scalar(select(Punch).where(Punch.user_id == user["id"]).order_by(Punch.ts.desc()))
        if last is not None:
            if (now - last.ts).total_seconds() < 60:
                raise HTTPException(400, "Timbratura troppo ravvicinata. Attendi almeno 60 secondi.")
            kind = "USCITA" if last.kind == "ENTRATA" else "ENTRATA"
        else:
            kind = "ENTRATA"
        s.add(Punch(user_id=user["id"], ts=now, kind=kind, qr_token_hash=token_hash(req.token)))
        qr.used = True
        s.commit()
    return {"kind": kind, "timestamp": now.astimezone(TZ).strftime("%d/%m/%Y %H:%M:%S"), "name": user["name"]}


def previous_month_visible():
    now = datetime.now(TZ)
    if now.day > 6:
        return None
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_end = first - timedelta(seconds=1)
    prev_start = prev_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return prev_start.astimezone(timezone.utc), first.astimezone(timezone.utc), prev_start.strftime("%m/%Y")

@app.get("/api/me")
def me(session: str):
    return current(session)

@app.get("/api/my-punches")
def my_punches(session: str):
    user = current(session)
    if user["role"] != "employee":
        raise HTTPException(403, "Solo dipendenti")
    visible = previous_month_visible()
    if visible is None:
        return {"visible": False, "punches": []}
    start, end, month = visible
    with Session(engine) as s:
        rows = s.scalars(select(Punch).where(Punch.user_id == user["id"], Punch.ts >= start, Punch.ts < end).order_by(Punch.ts)).all()
    return {"visible": True, "month": month, "punches": [{"ts": p.ts.astimezone(TZ).strftime("%d/%m/%Y %H:%M:%S"), "kind": p.kind} for p in rows]}

@app.get("/api/admin/punches")
def admin_punches(session: str):
    user = current(session)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin richiesto")
    with Session(engine) as s:
        rows = s.execute(select(Punch, User.name).join(User, User.id == Punch.user_id).order_by(Punch.ts.desc()).limit(1000)).all()
    return [{"id": p.id, "name": name, "ts": p.ts.astimezone(TZ).isoformat(), "kind": p.kind, "edited": p.edited} for p, name in rows]

@app.get("/api/admin/users")
def users(session: str):
    user = current(session)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin richiesto")
    with Session(engine) as s:
        rows = s.scalars(select(User).order_by(User.name)).all()
    return [{"id": u.id, "name": u.name, "username": u.username, "role": u.role, "active": u.active} for u in rows]

@app.post("/api/admin/users")
def create_user(req: UserIn, session: str):
    user = current(session)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin richiesto")
    if req.role not in ("employee", "admin"):
        raise HTTPException(400, "Ruolo non valido")
    with Session(engine) as s:
        if s.scalar(select(User).where(User.username == req.username)) is not None:
            raise HTTPException(400, "Username già esistente")
        s.add(User(name=req.name, username=req.username, password_hash=hash_password(req.password), role=req.role))
        s.commit()
    return {"ok": True}

app.mount("/static", StaticFiles(directory="backend/static"), name="static")

@app.get("/")
def root():
    return FileResponse("backend/static/index.html"
