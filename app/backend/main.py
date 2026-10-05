import io
import os
import secrets
import hashlib
import hmac
import base64
from datetime import datetime
from html import escape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import qrcode
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text
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

@app.get("/qr", response_class=HTMLResponse)
def qr_page(request: Request):
    """Permanent QR page for the company tablet."""
    base_url = str(request.base_url).rstrip("/")
    target = f"{base_url}/"
    qr = qrcode.QRCode(version=1, box_size=12, border=4)
    qr.add_data(target)
    qr.make(fit=True)
    img = qr.make_image()
    import io, base64
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    return HTMLResponse(f"""<!doctype html>
<html lang="it">
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cascina Nascosta - QR</title>
<style>
html,body{{margin:0;min-height:100%;font-family:Arial,sans-serif;background:#f7f4ee;color:#242424}}
body{{display:flex;align-items:center;justify-content:center;text-align:center}}
main{{padding:30px;max-width:900px}}
h1{{font-size:clamp(28px,5vw,52px);margin:0 0 8px}}
h2{{font-size:clamp(18px,3vw,28px);font-weight:400;margin:0 0 28px}}
img{{width:min(70vw,560px);height:auto;background:white;padding:18px;border-radius:18px;box-shadow:0 8px 30px rgba(0,0,0,.12)}}
p{{font-size:20px;margin-top:24px}}
button{{font-size:18px;padding:12px 20px;border:0;border-radius:10px;cursor:pointer}}
</style>
</head>
<body>
<main>
<h1>Cascina Nascosta</h1>
<h2>TIMBRATURA DIPENDENTI</h2>
<img src="data:image/png;base64,{data}" alt="QR Code timbratura">
<p>Scansiona il QR code con il tuo telefono per timbrare.</p>
<button onclick="document.documentElement.requestFullscreen?.()">Schermo intero</button>
</main>
</body>
</html>""")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    username = Column(String(80), unique=True, nullable=False, index=True)
    pin_hash = Column(String(255), nullable=False)
    team = Column(String(30), nullable=False, default="Sala")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(TZ).replace(tzinfo=None))
    entries = relationship("TimeEntry", back_populates="employee", cascade="all, delete-orphan")

class TimeEntry(Base):
    __tablename__ = "time_entries"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    kind = Column(String(10), nullable=False)
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

def hash_pin(pin):
    return pwd.hash(pin)

def check_pin(pin, hashed):
    try:
        return pwd.verify(pin, hashed)
    except Exception:
        return False

def admin_secret():
    return os.getenv("ADMIN_PASSWORD", "").strip()

def make_admin_token():
    secret = admin_secret()
    if not secret:
        return ""
    raw = "admin:" + secret
    sig = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode((raw + ":" + sig).encode()).decode()

def is_admin(request):
    expected = make_admin_token()
    return bool(expected and hmac.compare_digest(request.cookies.get("cn_admin", ""), expected))

def require_admin(request):
    if not is_admin(request):
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})

def current_employee(request, db):
    raw = request.cookies.get("cn_employee")
    if not raw or not raw.isdigit():
        return None
    return db.query(Employee).filter(Employee.id == int(raw), Employee.active == True).first()

def esc(value):
    return escape(str(value or ""), quote=True)

def layout(title, body, admin=False):
    nav = ""
    if admin:
        nav = '''<header class="topbar"><a class="brand" href="/admin"><span class="brand-mark">CN</span><span>Cascina Nascosta</span></a><nav><a href="/admin">Dashboard</a><a href="/admin/report">Presenze</a><a href="/admin/qr">QR</a><a href="/logout">Esci</a></nav></header>'''
    return HTMLResponse(f'''<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#23483a"><link rel="manifest" href="/static/manifest.json"><link rel="stylesheet" href="/static/style.css"><title>{esc(title)} — Cascina Nascosta</title></head>
<body>{nav}<main class="container">{body}</main><script src="/static/app.js"></script></body></html>''')

@app.get("/", response_class=HTMLResponse)
def home():
    return layout("Accesso", '''<section class="home"><div class="logo-circle">CN</div><div class="home-name">Cascina Nascosta</div><div class="home-subtitle">Gestione presenze</div><a class="home-button" href="/login">Accesso dipendente</a></section>''')

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return layout("Accesso dipendente", '''<section class="auth-card card"><div class="eyebrow">CASCINA NASCOSTA</div><h1>Accesso dipendente</h1><form method="post" action="/login"><label>Nome utente<input name="username" required autocomplete="username" autocapitalize="none"></label><label>PIN<input name="pin" type="password" inputmode="numeric" pattern="[0-9]*" required autocomplete="current-password"></label><label class="remember"><input type="checkbox" name="remember" value="1"> <span>Salva le credenziali su questo dispositivo</span></label><button class="primary">Accedi</button></form><p class="muted center">Per problemi di accesso chiedi all'amministratore.</p></section>''')

@app.post("/login")
def login(username: str = Form(...), pin: str = Form(...), remember: str = Form(""), db: Session = Depends(db)):
    emp = db.query(Employee).filter(Employee.username == username.strip().lower(), Employee.active == True).first()
    if not emp or not check_pin(pin, emp.pin_hash):
        return layout("Accesso", '''<section class="auth-card card"><div class="error">Nome utente o PIN non corretti.</div><a class="button" href="/login">Riprova</a></section>''')
    r = RedirectResponse("/employee", status_code=303)
    r.set_cookie("cn_employee", str(emp.id), httponly=True, samesite="lax", secure=True, max_age=2592000 if remember else None)
    return r

@app.get("/employee", response_class=HTMLResponse)
def employee_page(request: Request, db: Session = Depends(db)):
    emp = current_employee(request, db)
    if not emp:
        return RedirectResponse("/login", status_code=303)
    last = db.query(TimeEntry).filter(TimeEntry.employee_id == emp.id).order_by(TimeEntry.timestamp.desc()).first()
    inside = bool(last and last.kind == "IN")
    label = "TIMBRA USCITA" if inside else "TIMBRA ENTRATA"
    status = "IN SERVIZIO" if inside else "NON IN SERVIZIO"
    cls = "status-on" if inside else "status-off"
    return layout("Area dipendente", f'''<section class="employee-head"><div><div class="eyebrow">AREA DIPENDENTE</div><h1>Ciao, {esc(emp.name)}</h1><p>{esc(emp.team)}</p></div><a class="button ghost" href="/logout">Esci</a></section><section class="card punch-card"><div class="status {cls}">{status}</div><div id="clock" class="clock">--:--:--</div><form method="post" action="/employee/punch"><button class="punch-button {'punch-out' if inside else ''}">{label}</button></form>{f'<p class="last">Ultima timbratura: {last.timestamp.strftime("%d/%m/%Y %H:%M")}</p>' if last else ''}</section><section class="card"><div class="card-head"><h2>Le mie timbrature</h2><a class="button secondary" href="/employee/history">Storico</a></div><p class="muted">Le tue timbrature sono salvate nel database.</p></section>''')

@app.post("/employee/punch")
def punch(request: Request, db: Session = Depends(db)):
    emp = current_employee(request, db)
    if not emp:
        return RedirectResponse("/login", status_code=303)
    last = db.query(TimeEntry).filter(TimeEntry.employee_id == emp.id).order_by(TimeEntry.timestamp.desc()).first()
    kind = "OUT" if last and last.kind == "IN" else "IN"
    db.add(TimeEntry(employee_id=emp.id, timestamp=now_local(), kind=kind))
    db.commit()
    return RedirectResponse("/employee", status_code=303)

@app.get("/employee/history", response_class=HTMLResponse)
def employee_history(request: Request, db: Session = Depends(db)):
    emp = current_employee(request, db)
    if not emp:
        return RedirectResponse("/login", status_code=303)
    rows = db.query(TimeEntry).filter(TimeEntry.employee_id == emp.id).order_by(TimeEntry.timestamp.desc()).limit(200).all()
    trs = "".join(f'<tr><td>{r.timestamp.strftime("%d/%m/%Y")}</td><td>{r.timestamp.strftime("%H:%M:%S")}</td><td><span class="badge {"in" if r.kind=="IN" else "out"}">{"Entrata" if r.kind=="IN" else "Uscita"}</span></td></tr>' for r in rows)
    return layout("Storico", f'''<section class="card"><div class="card-head"><h1>Storico</h1><a class="button secondary" href="/employee">Indietro</a></div><p class="muted">{esc(emp.name)}</p><div class="table-wrap"><table><thead><tr><th>Data</th><th>Ora</th><th>Tipo</th></tr></thead><tbody>{trs or '<tr><td colspan="3">Nessuna timbratura</td></tr>'}</tbody></table></div></section>''')

@app.get("/scan", response_class=HTMLResponse)
def scan_page():
    return layout("Timbratura", '''<section class="auth-card card"><div class="logo-circle small">CN</div><h1>Timbratura</h1><p class="muted">Accedi con il tuo nome utente e PIN per timbrare.</p><a class="home-button" href="/login">Accesso dipendente</a></section>''')

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login():
    return layout("Amministrazione", '''<section class="auth-card card"><div class="eyebrow">CASCINA NASCOSTA</div><h1>Amministrazione</h1><form method="post"><label>Password amministratore<input name="password" type="password" required autocomplete="current-password"></label><button class="primary">Accedi</button></form></section>''')

@app.post("/admin/login")
def admin_login_post(password: str = Form(...)):
    expected = admin_secret()
    if not expected or not secrets.compare_digest(password, expected):
        return layout("Amministrazione", '''<section class="auth-card card"><div class="error">Password non valida.</div><a class="button" href="/admin/login">Riprova</a></section>''')
    r = RedirectResponse("/admin", status_code=303)
    r.set_cookie("cn_admin", make_admin_token(), httponly=True, samesite="lax", secure=True, max_age=86400)
    return r

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(db)):
    require_admin(request)
    employees = db.query(Employee).order_by(Employee.active.desc(), Employee.name.asc()).all()
    active_count = sum(1 for e in employees if e.active)
    inside_ids = {x.employee_id for x in db.query(TimeEntry).filter(TimeEntry.timestamp >= datetime(now_local().year, now_local().month, now_local().day)).all() if x.kind == "IN"}
    # Last state wins, not any IN of the day.
    states = {}
    for x in db.query(TimeEntry).order_by(TimeEntry.timestamp.asc()).all(): states[x.employee_id] = x.kind == "IN"
    inside_count = sum(1 for e in employees if states.get(e.id, False) and e.active)
    rows = ""
    for e in employees:
        rows += f'''<tr><td><strong>{esc(e.name)}</strong></td><td>{esc(e.username)}</td><td>{esc(e.team)}</td><td><span class="badge {"in" if states.get(e.id,False) else "off"}">{"IN SERVIZIO" if states.get(e.id,False) else "FUORI"}</span></td><td><span class="badge {"in" if e.active else "off"}">{"Attivo" if e.active else "Disattivo"}</span></td><td><a class="small-button" href="/admin/edit/{e.id}">Modifica</a> <form class="inline" method="post" action="/admin/toggle/{e.id}"><button class="small-button">{"Disattiva" if e.active else "Riattiva"}</button></form></td></tr>'''
    return layout("Dashboard", f'''<section class="admin-hero"><div><div class="eyebrow">CASCINA NASCOSTA</div><h1>Amministrazione</h1><p>Gestione dipendenti e presenze</p></div><a class="button" href="/admin/qr">Mostra QR</a></section><section class="stats"><div class="stat"><span>Dipendenti</span><strong>{active_count}</strong></div><div class="stat"><span>In servizio</span><strong>{inside_count}</strong></div><div class="stat"><span>Totale account</span><strong>{len(employees)}</strong></div></section><div class="admin-grid"><section class="card"><h2>Nuovo dipendente</h2><form method="post" action="/admin/employees"><label>Nome e cognome<input name="name" required></label><label>Username<input name="username" required autocapitalize="none"></label><label>PIN<input name="pin" inputmode="numeric" pattern="[0-9]+" minlength="4" required></label><label>Team<select name="team"><option>Sala</option><option>Cucina</option><option>Altro</option></select></label><button class="primary">Aggiungi dipendente</button></form></section><section class="card wide"><div class="card-head"><h2>Dipendenti</h2><a class="button secondary" href="/admin/report">Presenze / Excel</a></div><div class="table-wrap"><table><thead><tr><th>Nome</th><th>Username</th><th>Team</th><th>Stato</th><th>Account</th><th></th></tr></thead><tbody>{rows or '<tr><td colspan="6">Nessun dipendente</td></tr>'}</tbody></table></div></section></div>''', admin=True)

@app.post("/admin/employees")
def add_employee(request: Request, name: str = Form(...), username: str = Form(...), pin: str = Form(...), team: str = Form(...), db: Session = Depends(db)):
    require_admin(request)
    username = username.strip().lower()
    if db.query(Employee).filter(Employee.username == username).first():
        return layout("Errore", '<section class="card"><div class="error">Username già esistente.</div><a class="button" href="/admin">Torna all’amministrazione</a></section>', admin=True)
    db.add(Employee(name=name.strip(), username=username, pin_hash=hash_pin(pin.strip()), team=team))
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/admin/edit/{employee_id}", response_class=HTMLResponse)
def edit_employee(employee_id: int, request: Request, db: Session = Depends(db)):
    require_admin(request)
    e = db.get(Employee, employee_id)
    if not e: raise HTTPException(404)
    return layout("Modifica dipendente", f'''<section class="card narrow"><div class="card-head"><h1>Modifica dipendente</h1><a class="button secondary" href="/admin">Indietro</a></div><form method="post"><label>Nome<input name="name" value="{esc(e.name)}" required></label><label>Username<input name="username" value="{esc(e.username)}" required></label><label>Nuovo PIN <span class="muted">lascia vuoto per non cambiarlo</span><input name="pin" inputmode="numeric" pattern="[0-9]*"></label><label>Team<select name="team"><option {'selected' if e.team=='Sala' else ''}>Sala</option><option {'selected' if e.team=='Cucina' else ''}>Cucina</option><option {'selected' if e.team=='Altro' else ''}>Altro</option></select></label><button class="primary">Salva modifiche</button></form></section>''', admin=True)

@app.post("/admin/edit/{employee_id}")
def edit_employee_post(employee_id: int, request: Request, name: str = Form(...), username: str = Form(...), pin: str = Form(""), team: str = Form(...), db: Session = Depends(db)):
    require_admin(request)
    e = db.get(Employee, employee_id)
    if not e: raise HTTPException(404)
    username = username.strip().lower()
    other = db.query(Employee).filter(Employee.username == username, Employee.id != employee_id).first()
    if other:
        return layout("Errore", '<section class="card"><div class="error">Username già esistente.</div><a class="button" href="/admin">Torna all’amministrazione</a></section>', admin=True)
    e.name = name.strip(); e.username = username; e.team = team
    if pin.strip(): e.pin_hash = hash_pin(pin.strip())
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/toggle/{employee_id}")
def toggle_employee(employee_id: int, request: Request, db: Session = Depends(db)):
    require_admin(request)
    e = db.get(Employee, employee_id)
    if e: e.active = not e.active; db.commit()
    return RedirectResponse("/admin", status_code=303)

def paired_rows(db, employee_id=None, team=None, start=None, end=None):
    q = db.query(TimeEntry, Employee).join(Employee, Employee.id == TimeEntry.employee_id)
    if employee_id: q = q.filter(Employee.id == employee_id)
    if team: q = q.filter(Employee.team == team)
    if start: q = q.filter(TimeEntry.timestamp >= start)
    if end: q = q.filter(TimeEntry.timestamp < end)
    data = q.order_by(Employee.name, TimeEntry.timestamp).all()
    grouped = {}
    for entry, emp in data:
        grouped.setdefault((emp.id, entry.timestamp.date()), []).append(entry)
    return grouped

def month_bounds(year, month):
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end

def build_report_rows(db, grouped):
    rows=[]; totals={}
    for (eid, day), entries in sorted(grouped.items(), key=lambda x:(x[0][1], x[0][0])):
        emp=db.get(Employee,eid); i=0
        while i < len(entries):
            ins = entries[i] if entries[i].kind == "IN" else None
            out = entries[i+1] if ins and i+1<len(entries) and entries[i+1].kind=="OUT" else None
            if ins:
                hours=(out.timestamp-ins.timestamp).total_seconds()/3600 if out else 0
                rows.append((emp,day,ins,out,hours)); totals[eid]=totals.get(eid,0)+hours
            i += 2 if ins else 1
    return rows, totals

@app.get("/admin/report", response_class=HTMLResponse)
def report(request: Request, db: Session = Depends(db), year: int|None=None, month: int|None=None, team: str|None=None, employee_id: int|None=None):
    require_admin(request)
    n=now_local(); year=year or n.year; month=month or n.month
    start,end=month_bounds(year,month); grouped=paired_rows(db,employee_id,team,start,end); rows,totals=build_report_rows(db,grouped)
    trs="".join(f'<tr><td>{esc(emp.name)}</td><td>{day.strftime("%d/%m/%Y")}</td><td>{ins.timestamp.strftime("%H:%M")}</td><td>{out.timestamp.strftime("%H:%M") if out else "—"}</td><td>{hours:.2f}</td></tr>' for emp,day,ins,out,hours in rows)
    employees=db.query(Employee).order_by(Employee.name).all()
    emp_opts=''.join(f'<option value="{e.id}" {"selected" if employee_id==e.id else ""}>{esc(e.name)}</option>' for e in employees)
    total=sum(totals.values())
    qs=urlencode({"year":year,"month":month,"team":team or ""})
    return layout("Presenze", f'''<section class="card"><div class="card-head"><div><div class="eyebrow">PRESENZE</div><h1>{month:02d}/{year}</h1></div><div><a class="button" href="/admin/export.xlsx?{qs}">Scarica Excel</a> <a class="button secondary" href="/admin">Dashboard</a></div></div><form class="filters" method="get"><label>Anno<input name="year" type="number" value="{year}"></label><label>Mese<input name="month" type="number" min="1" max="12" value="{month}"></label><label>Team<select name="team"><option value="">Tutti</option><option {'selected' if team=='Sala' else ''}>Sala</option><option {'selected' if team=='Cucina' else ''}>Cucina</option><option {'selected' if team=='Altro' else ''}>Altro</option></select></label><label>Dipendente<select name="employee_id"><option value="">Tutti</option>{emp_opts}</select></label><button>Filtra</button></form><div class="table-wrap"><table><thead><tr><th>Dipendente</th><th>Data</th><th>Entrata</th><th>Uscita</th><th>Ore</th></tr></thead><tbody>{trs or '<tr><td colspan="5">Nessuna timbratura nel periodo.</td></tr>'}</tbody></table></div><div class="summary">Totale ore visualizzate: <strong>{total:.2f}</strong></div></section>''', admin=True)

@app.get("/admin/export.xlsx")
def export_xlsx(request: Request, year: int, month: int, team: str = "", employee_id: int|None=None, db: Session = Depends(db)):
    require_admin(request)
    start,end=month_bounds(year,month); grouped=paired_rows(db,employee_id,team or None,start,end); rows,totals=build_report_rows(db,grouped)
    wb=Workbook(); ws=wb.active; ws.title="Timbrature"; ws.append(["Dipendente","Team","Data","Entrata","Uscita","Totale ore"])
    for emp,day,ins,out,hours in rows: ws.append([emp.name,emp.team,day,ins.timestamp.time(),out.timestamp.time() if out else None,round(hours,2)])
    ws2=wb.create_sheet("Riepilogo mensile"); ws2.append(["Dipendente","Team","Totale ore mese"])
    for eid,h in sorted(totals.items(), key=lambda x:db.get(Employee,x[0]).name):
        e=db.get(Employee,eid); ws2.append([e.name,e.team,round(h,2)])
    for sh in wb.worksheets:
        sh.freeze_panes="A2"
        for col in sh.columns:
            maxlen=max(len(str(c.value or "")) for c in col); sh.column_dimensions[col[0].column_letter].width=min(maxlen+2,30)
    out=io.BytesIO(); wb.save(out); out.seek(0)
    return StreamingResponse(out,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":f'attachment; filename="timbrature_{year}_{month:02d}.xlsx"'})

@app.get("/admin/qr", response_class=HTMLResponse)
def admin_qr(request: Request):
    require_admin(request)
    return layout("QR Code", '''<section class="card qr-card"><div class="eyebrow">TIMBRATURA</div><h1>QR Code dipendenti</h1><p class="muted">I dipendenti possono scansionare questo QR per aprire direttamente la pagina di accesso alla timbratura.</p><div class="qr-frame"><img src="/admin/qr.png" alt="QR Code per la timbratura"></div><p class="url" id="qr-url"></p><button class="button" onclick="window.print()">Stampa QR</button><a class="button secondary" href="/admin">Torna alla dashboard</a></section>''', admin=True)

@app.get("/admin/qr.png")
def admin_qr_png(request: Request):
    require_admin(request)
    base = str(request.base_url).rstrip("/")
    target = base + "/scan"
    img = qrcode.make(target)
    out=io.BytesIO(); img.save(out,format="PNG"); out.seek(0)
    return StreamingResponse(out,media_type="image/png",headers={"Cache-Control":"no-store"})

@app.get("/health")
def health():
    return {"status":"ok"}

@app.get("/api/status")
def api_status():
    return {"ok":True,"app":"timbrature-pwa"}
