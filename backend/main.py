import os
import io
import secrets
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Date, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from passlib.context import CryptContext
from openpyxl import Workbook

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

TZ = ZoneInfo(os.getenv("TZ", "Europe/Rome"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./timbrature.db"
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_kwargs = {"pool_pre_ping": True} if DATABASE_URL.startswith("postgresql") else {"connect_args": {"check_same_thread": False}}
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="Timbrature — Cascina Nascosta")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    username = Column(String(80), unique=True, nullable=False, index=True)
    pin_hash = Column(String(255), nullable=False)
    team = Column(String(30), nullable=False, default="Sala")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(TZ))

    entries = relationship("TimeEntry", back_populates="employee", cascade="all, delete-orphan")

class TimeEntry(Base):
    __tablename__ = "time_entries"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    kind = Column(String(10), nullable=False)  # IN / OUT
    note = Column(Text, nullable=True)

    employee = relationship("Employee", back_populates="entries")

Base.metadata.create_all(engine)

def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

def now_local():
    return datetime.now(TZ).replace(tzinfo=None)

def hash_pin(pin: str) -> str:
    return pwd.hash(pin)

def check_pin(pin: str, hashed: str) -> bool:
    try:
        return pwd.verify(pin, hashed)
    except Exception:
        return False

def seed_admin():
    # Admin credentials are environment-controlled and are never exposed in the UI.
    # Employee accounts can be created from the admin area.
    pass

seed_admin()

def page(title, body, admin=False):
    nav = """
    <header class="topbar">
      <div class="brand"><span class="brand-mark">CN</span><span>Cascina Nascosta</span></div>
      <div class="nav-links">
        <a href="/">Timbrature</a>
        <a href="/admin">Admin</a>
      </div>
    </header>
    """
    return HTMLResponse(f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#28483b">
<link rel="stylesheet" href="/static/style.css">
<title>{title}</title>
</head>
<body>{nav}<main class="container">{body}</main></body></html>""")

def get_admin(request: Request):
    return request.cookies.get("cn_admin") == "1"

def require_admin(request: Request):
    if not get_admin(request):
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})

@app.get("/", response_class=HTMLResponse)
def home():
    return page("Timbrature", """
    <section class="hero">
      <div>
        <div class="eyebrow">GESTIONE PRESENZE</div>
        <h1>Timbrature</h1>
        <p>Accedi all'area dipendente per registrare entrata e uscita.</p>
      </div>
      <div class="hero-badge">CASCINA<br>NAScosta</div>
    </section>
    <div class="card login-card">
      <h2>Area dipendente</h2>
      <form method="post" action="/login">
        <label>Utente<input name="username" required autocomplete="username"></label>
        <label>PIN<input name="pin" type="password" inputmode="numeric" required autocomplete="current-password"></label>
        <button class="primary">Accedi</button>
      </form>
      <p class="muted">Se le credenziali non funzionano, chiedi all'amministratore di reimpostare il PIN.</p>
    </div>
    """)

@app.post("/login")
def login(username: str = Form(...), pin: str = Form(...), db: Session = Depends(db)):
    emp = db.query(Employee).filter(Employee.username == username.strip().lower(), Employee.active == True).first()
    if not emp or not check_pin(pin, emp.pin_hash):
        return page("Accesso", """<div class="card"><h2>Credenziali non valide</h2><p>Utente o PIN non corretti.</p><a class="button" href="/">Torna al login</a></div>""")
    r = RedirectResponse("/employee", status_code=303)
    r.set_cookie("cn_employee", str(emp.id), httponly=True, samesite="lax", secure=False, max_age=86400)
    return r

def current_employee(request: Request, db: Session):
    raw = request.cookies.get("cn_employee")
    if not raw or not raw.isdigit():
        return None
    return db.query(Employee).filter(Employee.id == int(raw), Employee.active == True).first()

@app.get("/employee", response_class=HTMLResponse)
def employee_page(request: Request, db: Session = Depends(db)):
    emp = current_employee(request, db)
    if not emp:
        return RedirectResponse("/", status_code=303)
    last = db.query(TimeEntry).filter(TimeEntry.employee_id == emp.id).order_by(TimeEntry.timestamp.desc()).first()
    status = "ENTRATA" if last and last.kind == "IN" else "USCITA"
    label = "TIMBRA ENTRATA" if status == "USCITA" else "TIMBRA USCITA"
    return page("Area dipendente", f"""
    <section class="hero compact">
      <div><div class="eyebrow">AREA DIPENDENTE</div><h1>Ciao, {emp.name}</h1><p>{emp.team}</p></div>
    </section>
    <div class="card punch-card">
      <div class="status-pill {'on' if status=='ENTRATA' else ''}">Ultimo stato: {status}</div>
      <div id="clock" class="clock"></div>
      <form method="post" action="/employee/punch">
        <button class="punch {'out' if status=='ENTRATA' else ''}" type="submit">{label}</button>
      </form>
      <a class="logout" href="/logout">Esci</a>
    </div>
    <div class="card">
      <h2>Le mie timbrature</h2>
      <p class="muted">Le timbrature vengono salvate nel database e rimangono disponibili per l'amministrazione.</p>
      <a class="button" href="/employee/history">Vedi storico</a>
    </div>
    <script>
      function tick(){document.getElementById('clock').textContent=new Date().toLocaleTimeString('it-IT',{{hour:'2-digit',minute:'2-digit',second:'2-digit'}});}
      tick(); setInterval(tick,1000);
    </script>
    """)

@app.post("/employee/punch")
def punch(request: Request, db: Session = Depends(db)):
    emp = current_employee(request, db)
    if not emp:
        return RedirectResponse("/", status_code=303)
    last = db.query(TimeEntry).filter(TimeEntry.employee_id == emp.id).order_by(TimeEntry.timestamp.desc()).first()
    kind = "OUT" if last and last.kind == "IN" else "IN"
    db.add(TimeEntry(employee_id=emp.id, timestamp=now_local(), kind=kind))
    db.commit()
    return RedirectResponse("/employee", status_code=303)

@app.get("/employee/history", response_class=HTMLResponse)
def employee_history(request: Request, db: Session = Depends(db)):
    emp = current_employee(request, db)
    if not emp:
        return RedirectResponse("/", status_code=303)
    rows = db.query(TimeEntry).filter(TimeEntry.employee_id == emp.id).order_by(TimeEntry.timestamp.desc()).limit(100).all()
    trs = "".join(f"<tr><td>{r.timestamp.strftime('%d/%m/%Y')}</td><td>{r.timestamp.strftime('%H:%M:%S')}</td><td>{'Entrata' if r.kind=='IN' else 'Uscita'}</td></tr>" for r in rows)
    return page("Storico", f"""<div class="card"><h1>Storico — {emp.name}</h1><table><thead><tr><th>Data</th><th>Ora</th><th>Tipo</th></tr></thead><tbody>{trs}</tbody></table><a class="button" href="/employee">Indietro</a></div>""")

@app.get("/logout")
def logout():
    r = RedirectResponse("/", status_code=303)
    r.delete_cookie("cn_employee")
    r.delete_cookie("cn_admin")
    return r

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login():
    return page("Admin", """<div class="card login-card"><div class="eyebrow">AMMINISTRAZIONE</div><h1>Area admin</h1>
    <form method="post"><label>Password admin<input name="password" type="password" required></label><button class="primary">Accedi</button></form></div>""")

@app.post("/admin/login")
def admin_login_post(password: str = Form(...)):
    expected = os.getenv("ADMIN_PASSWORD", "")
    if not expected or not secrets.compare_digest(password, expected):
        return page("Admin", """<div class="card"><h2>Password non valida</h2><a class="button" href="/admin/login">Riprova</a></div>""")
    r = RedirectResponse("/admin", status_code=303)
    r.set_cookie("cn_admin", "1", httponly=True, samesite="lax", secure=False, max_age=86400)
    return r

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(db)):
    require_admin(request)
    employees = db.query(Employee).order_by(Employee.active.desc(), Employee.name.asc()).all()
    rows = ""
    for e in employees:
        action = "Disattiva" if e.active else "Riattiva"
        rows += f"""<tr><td>{e.name}</td><td>{e.username}</td><td>{e.team}</td><td>{'Attivo' if e.active else 'Disattivo'}</td>
        <td class="actions"><a class="small-button" href="/admin/edit/{e.id}">Modifica</a>
        <form method="post" action="/admin/toggle/{e.id}" style="display:inline"><button class="small-button">{action}</button></form></td></tr>"""
    return page("Admin", f"""
    <section class="hero compact"><div><div class="eyebrow">CASCINA NASCOSTA</div><h1>Amministrazione</h1><p>Dipendenti e presenze</p></div></section>
    <div class="admin-grid">
      <div class="card"><h2>Nuovo dipendente</h2>
      <form method="post" action="/admin/employees">
        <label>Nome e cognome<input name="name" required></label>
        <label>Username<input name="username" required></label>
        <label>PIN<input name="pin" inputmode="numeric" minlength="4" required></label>
        <label>Team<select name="team"><option>Sala</option><option>Cucina</option><option>Altro</option></select></label>
        <button class="primary">Aggiungi dipendente</button>
      </form></div>
      <div class="card wide"><div class="card-head"><h2>Dipendenti</h2><a class="button" href="/admin/report">Report</a></div>
      <table><thead><tr><th>Nome</th><th>Username</th><th>Team</th><th>Stato</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
    </div>
    """)

@app.post("/admin/employees")
def add_employee(request: Request, name: str = Form(...), username: str = Form(...), pin: str = Form(...), team: str = Form(...), db: Session = Depends(db)):
    require_admin(request)
    username = username.strip().lower()
    if db.query(Employee).filter(Employee.username == username).first():
        raise HTTPException(400, "Username già esistente")
    db.add(Employee(name=name.strip(), username=username, pin_hash=hash_pin(pin), team=team))
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/admin/edit/{employee_id}", response_class=HTMLResponse)
def edit_employee(employee_id: int, request: Request, db: Session = Depends(db)):
    require_admin(request)
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404)
    return page("Modifica dipendente", f"""<div class="card"><h1>Modifica {e.name}</h1>
    <form method="post"><label>Nome<input name="name" value="{e.name}" required></label>
    <label>Username<input name="username" value="{e.username}" required></label>
    <label>Nuovo PIN <span class="muted">(lascia vuoto per non cambiarlo)</span><input name="pin" inputmode="numeric"></label>
    <label>Team<select name="team"><option {'selected' if e.team=='Sala' else ''}>Sala</option><option {'selected' if e.team=='Cucina' else ''}>Cucina</option><option {'selected' if e.team=='Altro' else ''}>Altro</option></select></label>
    <button class="primary">Salva</button></form><a class="button" href="/admin">Annulla</a></div>""")

@app.post("/admin/edit/{employee_id}")
def edit_employee_post(employee_id: int, request: Request, name: str = Form(...), username: str = Form(...), pin: str = Form(""), team: str = Form(...), db: Session = Depends(db)):
    require_admin(request)
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404)
    other = db.query(Employee).filter(Employee.username == username.strip().lower(), Employee.id != employee_id).first()
    if other:
        raise HTTPException(400, "Username già esistente")
    e.name = name.strip()
    e.username = username.strip().lower()
    e.team = team
    if pin.strip():
        e.pin_hash = hash_pin(pin.strip())
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/toggle/{employee_id}")
def toggle_employee(employee_id: int, request: Request, db: Session = Depends(db)):
    require_admin(request)
    e = db.get(Employee, employee_id)
    if e:
        e.active = not e.active
        db.commit()
    return RedirectResponse("/admin", status_code=303)

def paired_rows(db, employee_id=None, team=None, start=None, end=None):
    q = db.query(TimeEntry, Employee).join(Employee, Employee.id == TimeEntry.employee_id)
    if employee_id:
        q = q.filter(Employee.id == employee_id)
    if team:
        q = q.filter(Employee.team == team)
    if start:
        q = q.filter(TimeEntry.timestamp >= start)
    if end:
        q = q.filter(TimeEntry.timestamp < end)
    data = q.order_by(Employee.name, TimeEntry.timestamp).all()
    grouped = {}
    for entry, emp in data:
        d = entry.timestamp.date()
        key = (emp.id, d)
        grouped.setdefault(key, []).append(entry)
    return data, grouped

@app.get("/admin/report", response_class=HTMLResponse)
def report(request: Request, db: Session = Depends(db), year: int | None = None, month: int | None = None, team: str | None = None):
    require_admin(request)
    now = now_local()
    year = year or now.year
    month = month or now.month
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1)
    _, grouped = paired_rows(db, team=team, start=start, end=end)
    total = 0.0
    trs = ""
    for (eid, d), entries in sorted(grouped.items(), key=lambda x: (x[0][1], x[0][0])):
        emp = db.get(Employee, eid)
        for i in range(0, len(entries), 2):
            ins = entries[i]
            outs = entries[i+1] if i+1 < len(entries) and entries[i+1].kind == "OUT" else None
            hours = ((outs.timestamp - ins.timestamp).total_seconds()/3600) if outs else 0
            total += hours
            trs += f"<tr><td>{emp.name}</td><td>{d.strftime('%d/%m/%Y')}</td><td>{ins.timestamp.strftime('%H:%M')}</td><td>{outs.timestamp.strftime('%H:%M') if outs else '—'}</td><td>{hours:.2f}</td></tr>"
    return page("Report", f"""<div class="card"><div class="card-head"><div><div class="eyebrow">REPORT</div><h1>{month:02d}/{year}</h1></div>
    <a class="button" href="/admin/export.xlsx?year={year}&month={month}{'&team='+team if team else ''}">Scarica Excel</a></div>
    <form class="filters" method="get"><label>Anno<input name="year" value="{year}" type="number"></label><label>Mese<input name="month" value="{month}" type="number" min="1" max="12"></label>
    <label>Team<select name="team"><option value="">Tutti</option><option {'selected' if team=='Sala' else ''}>Sala</option><option {'selected' if team=='Cucina' else ''}>Cucina</option><option {'selected' if team=='Altro' else ''}>Altro</option></select></label><button class="small-button">Aggiorna</button></form>
    <table><thead><tr><th>Dipendente</th><th>Data</th><th>Entrata</th><th>Uscita</th><th>Ore</th></tr></thead><tbody>{trs}</tbody></table>
    <div class="summary">Totale mese: <strong>{total:.2f} ore</strong></div></div>""")

@app.get("/admin/export.xlsx")
def export_xlsx(request: Request, year: int, month: int, team: str = "", db: Session = Depends(db)):
    require_admin(request)
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1)
    _, grouped = paired_rows(db, team=team or None, start=start, end=end)
    wb = Workbook()
    ws = wb.active
    ws.title = "Timbrature"
    ws.append(["Dipendente", "Data", "Entrata", "Uscita", "Totale ore"])
    totals = {}
    for (eid, d), entries in sorted(grouped.items(), key=lambda x: (x[0][1], x[0][0])):
        emp = db.get(Employee, eid)
        for i in range(0, len(entries), 2):
            ins = entries[i]
            outs = entries[i+1] if i+1 < len(entries) and entries[i+1].kind == "OUT" else None
            hours = ((outs.timestamp - ins.timestamp).total_seconds()/3600) if outs else 0
            ws.append([emp.name, d, ins.timestamp.time(), outs.timestamp.time() if outs else None, round(hours, 2)])
            totals[eid] = totals.get(eid, 0) + hours
    # Only a monthly summary; no daily total row.
    ws2 = wb.create_sheet("Riepilogo mensile")
    ws2.append(["Dipendente", "Team", "Totale ore mese"])
    for eid, hours in sorted(totals.items(), key=lambda x: db.get(Employee, x[0]).name):
        emp = db.get(Employee, eid)
        ws2.append([emp.name, emp.team, round(hours, 2)])
    for sheet in (ws, ws2):
        for col in sheet.columns:
            maxlen = max(len(str(c.value or "")) for c in col)
            sheet.column_dimensions[col[0].column_letter].width = min(maxlen + 2, 28)
        sheet.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    filename = f"timbrature_{year}_{month:02d}.xlsx"
    return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/status")
def api_status():
    return {"ok": True, "app": "timbrature-pwa"}
