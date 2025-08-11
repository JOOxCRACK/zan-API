from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List, Optional
import secrets, sqlite3, json, os

app = FastAPI(title="BIN Uploader & Generator (separated)")

# ====== DB (SQLite بسيط، يشتغل محلي وعلى Render مع Persistent Disk) ======
DB_PATH = os.getenv("DB_PATH", "bins.db")

def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    con = db()
    con.execute("CREATE TABLE IF NOT EXISTS bins (prefix TEXT PRIMARY KEY)")
    con.commit()
    con.close()

init_db()

def save_bins(bins: List[str], mode: str):
    bins = _clean_bins(bins)
    con = db(); cur = con.cursor()
    if mode == "replace":
        cur.execute("DELETE FROM bins")
    for b in bins:
        cur.execute("INSERT OR IGNORE INTO bins(prefix) VALUES (?)", (b,))
    con.commit(); con.close()

def load_bins() -> List[str]:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT prefix FROM bins")
    rows = [r[0] for r in cur.fetchall()]
    con.close()
    return rows

def _clean_bins(bins: List[str]) -> List[str]:
    cleaned = []
    for b in bins or []:
        b = "".join(ch for ch in b if ch.isdigit())
        if b and 5 <= len(b) <= 12 and b not in cleaned:
            cleaned.append(b)
    if not cleaned:
        raise HTTPException(400, "لازم تبعت BINs صالحة (5–12 أرقام).")
    return cleaned

# ====== لوهِن + توليد ======
BIN_LEN_HINT = {"34":15,"37":15,"4":16,"51":16,"52":16,"53":16,"54":16,"55":16,"2":16,"6011":16,"65":16}

def infer_len(b: str) -> int:
    for p in sorted(BIN_LEN_HINT.keys(), key=len, reverse=True):
        if b.startswith(p): return BIN_LEN_HINT[p]
    return 16

def luhn_check_digit(number_without_check: str) -> str:
    digits = [int(d) for d in number_without_check]
    total = 0; parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9: d -= 9
        total += d
    return str((10 - (total % 10)) % 10)

def gen_pan(bin_str: str, length: int) -> str:
    body_len = length - len(bin_str) - 1
    body = "".join(str(secrets.randbelow(10)) for _ in range(body_len))
    partial = bin_str + body
    return partial + luhn_check_digit(partial)

# =======================
# Admin Router (رفع فقط)
# =======================
admin = APIRouter(prefix="/admin", tags=["admin"])
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@admin.get("/", response_class=HTMLResponse)
def upload_form(request: Request):
    count = len(load_bins())
    return templates.TemplateResponse("upload.html", {"request": request, "count": count})

@admin.post("/upload")
async def upload_bins(file: UploadFile = File(...), mode: str = Form("replace")):
    content = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".json"):
            bins = json.loads(content.decode("utf-8"))
            if not isinstance(bins, list):
                raise ValueError("JSON لازم يكون مصفوفة.")
        else:
            text = content.decode("utf-8")
            bins = [line.strip() for line in text.splitlines()]
        save_bins(bins, mode)
    except Exception as e:
        raise HTTPException(400, f"خطأ في قراءة الملف: {e}")
    return RedirectResponse(url="/admin/", status_code=303)

app.include_router(admin)

# =======================
# Public API (توليد فقط)
# =======================
class GenerateReq(BaseModel):
    count: int = Field(1, ge=1, le=100)
    no_consecutive_repeat: bool = True   # يمنع تكرار نفس BIN متتاليًا

class CardOut(BaseModel):
    pan: str
    masked: str
    bin_used: str
    note: str = "TEST USE ONLY – Luhn-valid"

@app.get("/api/health")
def health():
    return {"ok": True, "bins_count": len(load_bins())}

@app.post("/api/generate", response_model=List[CardOut])
def generate(req: GenerateReq):
    bins = load_bins()
    if not bins:
        raise HTTPException(400, "لا توجد BINs بعد. ارفعها من /admin/ أولًا.")
    out: List[CardOut] = []
    last_b = None
    for _ in range(req.count):
        # اختَر BIN عشوائي آمن
        b = secrets.choice(bins)
        if req.no_consecutive_repeat and last_b and len(bins) > 1 and b == last_b:
            # حاول تبديل واحد تاني غيره
            alt = b
            tries = 0
            while alt == b and tries < 8:
                alt = secrets.choice(bins)
                tries += 1
            b = alt
        last_b = b
        pan = gen_pan(b, infer_len(b))
        masked = pan[:6] + "******" + pan[-4:]
        out.append(CardOut(pan=pan, masked=masked, bin_used=b))
    return out
