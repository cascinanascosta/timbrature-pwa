
from __future__ import annotations

import csv
import io
import os
import secrets
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Time, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./cascina_local.db"
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    employees: Mapped[list["Employee"]] = relationship(back_populates="team")

class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    pin: Mapped[str] = mapped_column(String(20), nullable=False)
    team_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teams.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    team: Mapped[Optional[Team]] = relationship(back_populates="employees")
    entries: Mapped[list["TimeEntry"]] = relationship(back_populates="employee", cascade="all, delete-orphan")

class TimeEntry(Base):
    __tablename__ = "time_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    entry1: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    exit1: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    entry2: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    exit2: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    employee: Mapped[Employee] = relationship(back_populates="entries")

class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)

Base.metadata.create_all(engine)

def seed():
    with SessionLocal() as db:
        sala = db.query(Team).filter_by(name="Sala").first()
        cucina = db.query(Team).filter_by(name="Cucina").first()
        if not sala:
            sala = Team(name="Sala")
            db.add(sala)
        if not cucina:
            cucina = Team(name="Cucina")
            db.add(cucina)
        db.commit()
        # Keep the known test/admin credentials from the previous setup.
        jacopo = db.query(Employee).filter_by(name="Jacopo").first()
        if not jacopo:
            db.add(Employee(name="Jacopo", pin="1111", team_id=sala.id, active=True))
            db.commit()

seed()

app = FastAPI(title="Cascina Timbrature", version="2.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ADMIN_PIN = os.getenv("ADMIN_PIN", "1234")

def parse_t(v: Optional[str]) -> Optional[time]:
    if not v:
        return None
    try:
        h, m = v.split(":")[:2]
        return time(int(h), int(m))
    except Exception:
        raise HTTPException(400, "Orario non valido")

def mins(a: Optional[time], b: Optional[time]) -> int:
    if not a or not b:
        return 0
    start = a.hour * 60 + a.minute
    end = b.hour * 60 + b.minute
    if end < start:
        end += 24 * 60
    return end - start

def total_minutes(e: TimeEntry) -> int:
    return mins(e.entry1, e.exit1) + mins(e.entry2, e.exit2)

def fmt_minutes(n: int) -> str:
    return f"{n // 60}:{n % 60:02d}"

def auth_admin(pin: str):
    if not secrets.compare_digest(str(pin), str(ADMIN_PIN)):
        raise HTTPException(401, "PIN admin non valido")

@app.get("/", response_class=FileResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/employee", response_class=FileResponse)
def employee_page():
    return FileResponse(STATIC_DIR / "employee.html")

@app.get("/admin", response_class=FileResponse)
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")

@app.get("/qr", response_class=FileResponse)
def qr_page():
    return FileResponse(STATIC_DIR / "qr.html")

@app.get("/api/health")
def health():
    return {"ok": True, "database": DATABASE_URL.split("://", 1)[0]}

@app.post("/api/employee/login")
def employee_login(name: str = Form(...), pin: str = Form(...)):
    with SessionLocal() as db:
        emp = db.query(Employee).filter(func.lower(Employee.name) == name.strip().lower(),
                                        Employee.active == True).first()
        if not emp or not secrets.compare_digest(emp.pin, pin.strip()):
            raise HTTPException(401, "Credenziali non valide")
        return {"ok": True, "id": emp.id, "name": emp.name, "team": emp.team.name if emp.team else ""}

@app.post("/api/admin/login")
def admin_login(pin: str = Form(...)):
    auth_admin(pin)
    return {"ok": True}

@app.get("/api/teams")
def teams():
    with SessionLocal() as db:
        return [{"id": t.id, "name": t.name, "active": t.active} for t in db.query(Team).order_by(Team.name).all()]

@app.post("/api/teams")
def add_team(name: str = Form(...), pin: str = Form(...)):
    auth_admin(pin)
    name = name.strip()
    if not name:
        raise HTTPException(400, "Nome team obbligatorio")
    with SessionLocal() as db:
        if db.query(Team).filter(func.lower(Team.name) == name.lower()).first():
            raise HTTPException(409, "Team già esistente")
        t = Team(name=name, active=True)
        db.add(t)
        db.commit()
        db.refresh(t)
        return {"id": t.id, "name": t.name}

@app.delete("/api/teams/{team_id}")
def delete_team(team_id: int, pin: str = Query(...)):
    auth_admin(pin)
    with SessionLocal() as db:
        t = db.get(Team, team_id)
        if not t:
            raise HTTPException(404, "Team non trovato")
        if db.query(Employee).filter_by(team_id=team_id, active=True).count():
            raise HTTPException(400, "Il team ha dipendenti attivi")
        t.active = False
        db.commit()
        return {"ok": True}

@app.get("/api/employees")
def employees():
    with SessionLocal() as db:
        rows = db.query(Employee).order_by(Employee.name).all()
        return [{"id": e.id, "name": e.name, "pin": e.pin, "team_id": e.team_id,
                 "team": e.team.name if e.team else "", "active": e.active} for e in rows]

@app.post("/api/employees")
def add_employee(name: str = Form(...), pin: str = Form(...), team_id: int = Form(...), admin_pin: str = Form(...)):
    auth_admin(admin_pin)
    name, pin = name.strip(), pin.strip()
    if not name or not pin:
        raise HTTPException(400, "Nome e PIN obbligatori")
    with SessionLocal() as db:
        if db.query(Employee).filter(func.lower(Employee.name) == name.lower()).first():
            raise HTTPException(409, "Dipendente già esistente")
        if not db.get(Team, team_id):
            raise HTTPException(400, "Team non valido")
        e = Employee(name=name, pin=pin, team_id=team_id, active=True)
        db.add(e); db.commit(); db.refresh(e)
        return {"id": e.id, "name": e.name}

@app.put("/api/employees/{employee_id}")
def edit_employee(employee_id: int, name: str = Form(...), pin: str = Form(...),
                  team_id: int = Form(...), active: bool = Form(True), admin_pin: str = Form(...)):
    auth_admin(admin_pin)
    with SessionLocal() as db:
        e = db.get(Employee, employee_id)
        if not e:
            raise HTTPException(404, "Dipendente non trovato")
        e.name = name.strip()
        e.pin = pin.strip()
        e.team_id = team_id
        e.active = active
        db.commit()
        return {"ok": True}

@app.delete("/api/employees/{employee_id}")
def delete_employee(employee_id: int, pin: str = Query(...)):
    auth_admin(pin)
    with SessionLocal() as db:
        e = db.get(Employee, employee_id)
        if not e:
            raise HTTPException(404, "Dipendente non trovato")
        e.active = False
        db.commit()
        return {"ok": True}

@app.post("/api/punch/{employee_id}")
def punch(employee_id: int, pin: str = Form(...), when: Optional[str] = Form(None)):
    with SessionLocal() as db:
        e = db.get(Employee, employee_id)
        if not e or not e.active or not secrets.compare_digest(e.pin, pin.strip()):
            raise HTTPException(401, "Credenziali non valide")
        dt = datetime.fromisoformat(when) if when else datetime.now()
        d = dt.date()
        now = dt.time().replace(second=0, microsecond=0)
        row = db.query(TimeEntry).filter_by(employee_id=employee_id, work_date=d).first()
        if not row:
            row = TimeEntry(employee_id=employee_id, work_date=d, entry1=now)
            db.add(row)
            action = "entrata"
        elif row.entry1 and not row.exit1:
            row.exit1 = now; action = "uscita"
        elif row.entry2 and not row.exit2:
            row.exit2 = now; action = "uscita"
        elif row.exit1 and not row.entry2:
            row.entry2 = now; action = "entrata"
        else:
            raise HTTPException(400, "Turno del giorno già completo")
        db.commit()
        return {"ok": True, "action": action, "time": now.strftime("%H:%M"),
                "total": fmt_minutes(total_minutes(row))}

@app.get("/api/today/{employee_id}")
def today(employee_id: int):
    d = date.today()
    with SessionLocal() as db:
        row = db.query(TimeEntry).filter_by(employee_id=employee_id, work_date=d).first()
        if not row:
            return {"date": d.isoformat(), "entry1": None, "exit1": None, "entry2": None, "exit2": None, "total": "0:00"}
        return entry_json(row)

def entry_json(e: TimeEntry):
    return {"id": e.id, "date": e.work_date.isoformat(),
            "entry1": e.entry1.strftime("%H:%M") if e.entry1 else None,
            "exit1": e.exit1.strftime("%H:%M") if e.exit1 else None,
            "entry2": e.entry2.strftime("%H:%M") if e.entry2 else None,
            "exit2": e.exit2.strftime("%H:%M") if e.exit2 else None,
            "total": fmt_minutes(total_minutes(e))}

@app.get("/api/report")
def report(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
           employee_id: Optional[int] = None, team_id: Optional[int] = None,
           admin_pin: str = Query(...)):
    auth_admin(admin_pin)
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    last = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    with SessionLocal() as db:
        q = db.query(TimeEntry).join(Employee).filter(TimeEntry.work_date >= first, TimeEntry.work_date < last)
        if employee_id:
            q = q.filter(TimeEntry.employee_id == employee_id)
        if team_id:
            q = q.filter(Employee.team_id == team_id)
        rows = q.order_by(TimeEntry.work_date, Employee.name).all()
        return [dict(entry_json(r), employee_id=r.employee_id, employee=r.employee.name,
                      team=r.employee.team.name if r.employee.team else "") for r in rows]

@app.post("/api/admin/entry")
def admin_entry(employee_id: int = Form(...), work_date: str = Form(...),
                entry1: str = Form(""), exit1: str = Form(""),
                entry2: str = Form(""), exit2: str = Form(""),
                admin_pin: str = Form(...)):
    auth_admin(admin_pin)
    d = date.fromisoformat(work_date)
    with SessionLocal() as db:
        if not db.get(Employee, employee_id):
            raise HTTPException(404, "Dipendente non trovato")
        row = db.query(TimeEntry).filter_by(employee_id=employee_id, work_date=d).first()
        if not row:
            row = TimeEntry(employee_id=employee_id, work_date=d)
            db.add(row)
        row.entry1, row.exit1 = parse_t(entry1), parse_t(exit1)
        row.entry2, row.exit2 = parse_t(entry2), parse_t(exit2)
        db.commit()
        return entry_json(row)

@app.get("/api/export.xlsx")
def export_xlsx(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
                employee_id: Optional[int] = None, team_id: Optional[int] = None,
                admin_pin: str = Query(...)):
    auth_admin(admin_pin)
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    last = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    with SessionLocal() as db:
        eq = db.query(Employee).filter(Employee.active == True)
        if employee_id: eq = eq.filter(Employee.id == employee_id)
        if team_id: eq = eq.filter(Employee.team_id == team_id)
        emps = eq.order_by(Employee.name).all()
        rows = db.query(TimeEntry).filter(TimeEntry.work_date >= first, TimeEntry.work_date < last).all()
        by_key = {(r.work_date, r.employee_id): r for r in rows}

    wb = Workbook()
    ws = wb.active
    ws.title = "Mensile"
    headers = ["Data"]
    for e in emps:
        headers += [f"{e.name} E", f"{e.name} U", f"{e.name} T"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="5B6F63")
        c.alignment = Alignment(horizontal="center")
    cur = first
    while cur < last:
        row = [cur.strftime("%d/%m/%Y")]
        for e in emps:
            r = by_key.get((cur, e.id))
            row += [
                r.entry1.strftime("%H:%M") if r and r.entry1 else "",
                r.exit1.strftime("%H:%M") if r and r.exit1 else "",
                fmt_minutes(total_minutes(r)) if r else "0:00"
            ]
        ws.append(row)
        cur += timedelta(days=1)
    ws.column_dimensions["A"].width = 14
    for col in ws.columns:
        if col[0].column > 1:
            ws.column_dimensions[col[0].column_letter].width = 14

    total = wb.create_sheet("Totali")
    total.append(["Dipendente", "Team", "Ore mese"])
    for c in total[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E7A93B")
    for e in emps:
        tm = sum(total_minutes(r) for r in by_key.values() if r.employee_id == e.id)
        total.append([e.name, e.team.name if e.team else "", fmt_minutes(tm)])

    out = io.BytesIO()
    wb.save(out); out.seek(0)
    filename = f"cascina_timbrature_{month}.xlsx"
    return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.get("/api/qr-token")
def qr_token():
    # A short-lived token is generated for the QR display.
    return {"token": secrets.token_urlsafe(16), "expires_in": 5}

@app.get("/api/ping")
def ping():
    return {"ok": True}
