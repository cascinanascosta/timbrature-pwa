from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import csv, io, secrets, os

app = FastAPI(title="Cascina Nascosta - Timbrature")
TZ = ZoneInfo("Europe/Rome")
BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"

employees = {
    1: {"id": 1, "name": "Jacopo", "pin": "1111", "team": "Sala", "active": True},
    2: {"id": 2, "name": "Della", "pin": "1234", "team": "Sala", "active": True},
}
punches = []
qr_token = None
qr_created = None

class Login(BaseModel):
    name: str
    pin: str

class PunchRequest(BaseModel):
    employee_id: int
    token: str

class EmployeeCreate(BaseModel):
    name: str
    pin: str
    team: str

def now():
    return datetime.now(TZ)

def valid_qr(token):
    global qr_token, qr_created
    if qr_token is None or qr_created is None or token != qr_token:
        return False
    return (now() - qr_created).total_seconds() <= 5

def ensure_qr():
    global qr_token, qr_created
    if qr_token is None or qr_created is None or (now()-qr_created).total_seconds() >= 5:
        qr_token = secrets.token_urlsafe(18)
        qr_created = now()
    return qr_token

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

@app.get("/employee")
def employee_page():
    return FileResponse(STATIC / "employee.html")

@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html")

@app.get("/qr")
def qr_page():
    return FileResponse(STATIC / "qr.html")

@app.get("/api/qr")
def api_qr():
    return {"token": ensure_qr(), "expires_in": 5}

@app.post("/api/login")
def login(data: Login):
    for e in employees.values():
        if e["active"] and e["name"].lower() == data.name.lower() and e["pin"] == data.pin:
            return {"ok": True, "employee": e}
    raise HTTPException(401, "Credenziali non valide")

@app.post("/api/punch")
def punch(data: PunchRequest):
    if data.employee_id not in employees or not employees[data.employee_id]["active"]:
        raise HTTPException(404, "Dipendente non trovato")
    if not valid_qr(data.token):
        raise HTTPException(400, "QR scaduto o non valido")
    e = employees[data.employee_id]
    last = next((p for p in reversed(punches) if p["employee_id"] == e["id"]), None)
    typ = "USCITA" if last and last["tipo"] == "ENTRATA" else "ENTRATA"
    p = {"employee_id": e["id"], "timestamp": now().isoformat(), "tipo": typ}
    punches.append(p)
    return {"ok": True, "tipo": typ, "timestamp": p["timestamp"]}

@app.get("/api/employees")
def get_employees():
    return list(employees.values())

@app.post("/api/employees")
def create_employee(data: EmployeeCreate):
    new_id = max(employees.keys(), default=0) + 1
    employees[new_id] = {"id": new_id, "name": data.name, "pin": data.pin,
                         "team": data.team, "active": True}
    return employees[new_id]

@app.get("/api/report")
def report(year: int, month: int, employee_id: int | None = None, team: str | None = None):
    selected = [e for e in employees.values() if e["active"]]
    if employee_id:
        selected = [e for e in selected if e["id"] == employee_id]
    if team and team != "Tutti":
        selected = [e for e in selected if e["team"] == team]

    by_emp = {e["id"]: [] for e in selected}
    for p in punches:
        dt = datetime.fromisoformat(p["timestamp"])
        if dt.year == year and dt.month == month and p["employee_id"] in by_emp:
            by_emp[p["employee_id"]].append(p)

    # CSV: every employee occupies E/U/T columns; split shifts use two rows.
    out = io.StringIO()
    w = csv.writer(out)
    header = ["Data"]
    for e in selected:
        header += [f'{e["name"]} E', f'{e["name"]} U', f'{e["name"]} T']
    w.writerow(header)

    import calendar
    days = calendar.monthrange(year, month)[1]
    for d in range(1, days + 1):
        date_key = f"{year:04d}-{month:02d}-{d:02d}"
        rows = []
        max_rows = 1
        emp_pairs = {}
        for e in selected:
            ps = sorted(by_emp[e["id"]], key=lambda x:x["timestamp"])
            day = [p for p in ps if p["timestamp"][:10] == date_key]
            pairs=[]
            i=0
            while i < len(day)-1:
                if day[i]["tipo"]=="ENTRATA" and day[i+1]["tipo"]=="USCITA":
                    a=datetime.fromisoformat(day[i]["timestamp"])
                    b=datetime.fromisoformat(day[i+1]["timestamp"])
                    pairs.append((a,b))
                    i += 2
                else:
                    i += 1
            emp_pairs[e["id"]] = pairs
            max_rows=max(max_rows,len(pairs) or 1)

        for r in range(max_rows):
            row=[date_key]
            for e in selected:
                pairs=emp_pairs[e["id"]]
                if r < len(pairs):
                    a,b=pairs[r]
                    total=(b-a).total_seconds()/3600
                    row += [a.strftime("%H:%M"), b.strftime("%H:%M"), f"{total:.2f}"]
                else:
                    row += ["","",""]
            w.writerow(row)
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=timbrature_{year}_{month:02d}.csv"})

@app.get("/api/my-punches")
def my_punches(employee_id: int):
    # Employee visibility: previous month through day 6 of current month.
    n=now()
    cutoff = n.replace(hour=23,minute=59,second=59,microsecond=0)
    if n.day <= 6:
        start=(n.replace(day=1)-timedelta(days=1)).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        end=cutoff
    else:
        start=(n.replace(day=1)-timedelta(days=1)).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        end=(n.replace(day=1)-timedelta(seconds=1))
    return [p for p in punches if p["employee_id"]==employee_id and start <= datetime.fromisoformat(p["timestamp"]) <= end]
