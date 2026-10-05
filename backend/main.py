from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import csv, io, os, secrets

app = FastAPI(title="Cascina Nascosta - Timbrature")
TZ = ZoneInfo("Europe/Rome")
BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_INTERNAL_URL") or "sqlite:///./timbrature.db"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    pin = Column(String(20), nullable=False)
    team = Column(String(30), nullable=False, default="Sala")
    active = Column(Boolean, nullable=False, default=True)

class Punch(Base):
    __tablename__ = "punches"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    tipo = Column(String(20), nullable=False)

Base.metadata.create_all(engine)

def seed():
    db = SessionLocal()
    try:
        defaults = [("Jacopo", "1111", "Sala"), ("Della", "1234", "Sala")]
        for name, pin, team in defaults:
            if not db.query(Employee).filter(Employee.name.ilike(name)).first():
                db.add(Employee(name=name, pin=pin, team=team, active=True))
        db.commit()
    finally:
        db.close()
seed()

qr_token = None
qr_created = None

def now(): return datetime.now(TZ)

def emp_dict(e):
    return {"id": e.id, "name": e.name, "pin": e.pin, "team": e.team, "active": e.active}

def valid_qr(token):
    return bool(qr_token and qr_created and token == qr_token and (now()-qr_created).total_seconds() <= 5)

def ensure_qr():
    global qr_token, qr_created
    if qr_token is None or qr_created is None or (now()-qr_created).total_seconds() >= 5:
        qr_token, qr_created = secrets.token_urlsafe(18), now()
    return qr_token

class Login(BaseModel): name: str; pin: str
class PunchRequest(BaseModel): employee_id: int; token: str
class EmployeeCreate(BaseModel): name: str; pin: str; team: str
class EmployeeUpdate(BaseModel): name: str; pin: str; team: str; active: bool

@app.get("/")
def index(): return FileResponse(STATIC / "index.html")
@app.get("/employee")
def employee_page(): return FileResponse(STATIC / "employee.html")
@app.get("/admin")
def admin_page(): return FileResponse(STATIC / "admin.html")
@app.get("/qr")
def qr_page(): return FileResponse(STATIC / "qr.html")

@app.get("/api/qr")
def api_qr(): return {"token": ensure_qr(), "expires_in": 5}

@app.post("/api/login")
def login(data: Login):
    db=SessionLocal()
    try:
        e=db.query(Employee).filter(Employee.active == True, Employee.name.ilike(data.name.strip())).first()
        if not e or e.pin != data.pin.strip(): raise HTTPException(401, "Credenziali non valide")
        return {"ok":True,"employee":emp_dict(e)}
    finally: db.close()

@app.post("/api/punch")
def punch(data: PunchRequest):
    if not valid_qr(data.token): raise HTTPException(400, "QR scaduto o non valido")
    db=SessionLocal()
    try:
        e=db.get(Employee,data.employee_id)
        if not e or not e.active: raise HTTPException(404,"Dipendente non trovato")
        last=db.query(Punch).filter(Punch.employee_id==e.id).order_by(Punch.timestamp.desc()).first()
        typ="USCITA" if last and last.tipo=="ENTRATA" else "ENTRATA"
        p=Punch(employee_id=e.id,timestamp=now(),tipo=typ); db.add(p); db.commit(); db.refresh(p)
        return {"ok":True,"tipo":typ,"timestamp":p.timestamp.isoformat()}
    finally: db.close()

@app.get("/api/employees")
def get_employees():
    db=SessionLocal()
    try: return [emp_dict(e) for e in db.query(Employee).order_by(Employee.name).all()]
    finally: db.close()

@app.post("/api/employees")
def create_employee(data: EmployeeCreate):
    if data.team not in ("Sala","Cucina"): raise HTTPException(400,"Team non valido")
    db=SessionLocal()
    try:
        if db.query(Employee).filter(Employee.name.ilike(data.name.strip())).first(): raise HTTPException(409,"Dipendente già presente")
        e=Employee(name=data.name.strip(),pin=data.pin.strip(),team=data.team,active=True); db.add(e); db.commit(); db.refresh(e); return emp_dict(e)
    finally: db.close()

@app.put("/api/employees/{employee_id}")
def update_employee(employee_id:int,data:EmployeeUpdate):
    if data.team not in ("Sala","Cucina"): raise HTTPException(400,"Team non valido")
    db=SessionLocal()
    try:
        e=db.get(Employee,employee_id)
        if not e: raise HTTPException(404,"Dipendente non trovato")
        e.name=data.name.strip(); e.pin=data.pin.strip(); e.team=data.team; e.active=data.active
        db.commit(); db.refresh(e); return emp_dict(e)
    finally: db.close()

@app.delete("/api/employees/{employee_id}")
def delete_employee(employee_id:int):
    db=SessionLocal()
    try:
        e=db.get(Employee,employee_id)
        if not e: raise HTTPException(404,"Dipendente non trovato")
        e.active=False; db.commit(); return {"ok":True}
    finally: db.close()

@app.get("/api/my-punches")
def my_punches(employee_id:int):
    db=SessionLocal()
    try:
        n=now(); start=(n.replace(day=1)-timedelta(days=1)).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        end=n.replace(hour=23,minute=59,second=59,microsecond=0)
        rows=db.query(Punch).filter(Punch.employee_id==employee_id,Punch.timestamp>=start,Punch.timestamp<=end).order_by(Punch.timestamp.desc()).all()
        return [{"timestamp":p.timestamp.isoformat(),"tipo":p.tipo} for p in rows]
    finally: db.close()

def parse_pairs(items):
    pairs=[]; i=0
    while i<len(items)-1:
        if items[i].tipo=="ENTRATA" and items[i+1].tipo=="USCITA":
            pairs.append((items[i].timestamp,items[i+1].timestamp)); i+=2
        else: i+=1
    return pairs

@app.get("/api/report")
def report(year:int,month:int,employee_id:int|None=None,team:str|None=None):
    import calendar
    db=SessionLocal()
    try:
        q=db.query(Employee).filter(Employee.active==True)
        if employee_id: q=q.filter(Employee.id==employee_id)
        if team and team!="Tutti": q=q.filter(Employee.team==team)
        selected=q.order_by(Employee.name).all()
        ids=[e.id for e in selected]
        start=datetime(year,month,1,tzinfo=TZ); end=datetime(year,month,calendar.monthrange(year,month)[1],23,59,59,tzinfo=TZ)
        punches=db.query(Punch).filter(Punch.employee_id.in_(ids) if ids else False,Punch.timestamp>=start,Punch.timestamp<=end).order_by(Punch.timestamp).all()
        by={i:[] for i in ids}
        for p in punches: by[p.employee_id].append(p)
        out=io.StringIO(); w=csv.writer(out,delimiter=';')
        header=["Data"]
        for e in selected: header += [f"{e.name} E",f"{e.name} U",f"{e.name} T"]
        w.writerow(header)
        for d in range(1,calendar.monthrange(year,month)[1]+1):
            date_key=f"{year:04d}-{month:02d}-{d:02d}"; pairs={}; max_rows=1
            for e in selected:
                day=[p for p in by[e.id] if p.timestamp.astimezone(TZ).date().isoformat()==date_key]
                pairs[e.id]=parse_pairs(day); max_rows=max(max_rows,len(pairs[e.id]) or 1)
            for r in range(max_rows):
                row=[date_key]
                for e in selected:
                    pp=pairs[e.id]
                    if r<len(pp):
                        a,b=pp[r]; hours=(b-a).total_seconds()/3600
                        row += [a.astimezone(TZ).strftime('%H:%M'),b.astimezone(TZ).strftime('%H:%M'),f'{hours:.2f}']
                    else: row += ["","",""]
                w.writerow(row)
        return StreamingResponse(iter([out.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":f"attachment; filename=timbrature_{year}_{month:02d}.csv"})
    finally: db.close()
