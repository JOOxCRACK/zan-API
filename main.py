from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
import itertools, threading, json, secrets

app = FastAPI(title="BIN Generator")

# القائمة في الذاكرة + راوند روبن
CURRENT_BINS: list[str] = []
_lock = threading.Lock()
_cycle = None  # itertools.cycle
_last_bin = None

# --- Luhn + توليد ---
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

def _clean_bins(bins: list[str]) -> list[str]:
    out = []
    for b in bins or []:
        b = "".join(ch for ch in b if ch.isdigit())
        if b and 5 <= len(b) <= 12 and b not in out:
            out.append(b)
    return out

def _reset_cycle():
    global _cycle
    _cycle = itertools.cycle(CURRENT_BINS) if CURRENT_BINS else None

class CardOut(BaseModel):
    pan: str
    masked: str
    bin_used: str
    note: str = "TEST USE ONLY – Luhn-valid"

# ---------- صفحات/نهايات ----------
@app.get("/", response_class=HTMLResponse)
def upload_page():
    count = len(CURRENT_BINS)
    return f"""
<!doctype html><meta charset="utf-8">
<title>رفع BINs</title>
<h1>رفع BINs</h1>
<p>المسجّل حاليًا: <b>{count}</b> BIN(s)</p>
<form action="/upload" method="post" enctype="multipart/form-data">
  <label>ملف (JSON أو TXT/CSV – كل سطر BIN)</label><br>
  <input type="file" name="file" required>
  <br><label>النمط</label>
  <select name="mode"><option value="replace">استبدال</option><option value="append">إضافة</option></select>
  <br><button type="submit">رفع</button>
</form>
<p>توليد بطاقة: <code>GET /generate</code></p>
"""

@app.post("/upload")
async def upload_bins(file: UploadFile = File(...), mode: str = Form("replace")):
    content = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".json"):
            data = json.loads(content.decode("utf-8"))
            if not isinstance(data, list): raise ValueError("JSON لازم يكون مصفوفة.")
            bins = data
        else:
            text = content.decode("utf-8", errors="ignore")
            bins = [line.strip() for line in text.splitlines()]
        bins = _clean_bins(bins)
        if not bins: raise ValueError("لا توجد BINs صالحة (5–12 أرقام).")
    except Exception as e:
        raise HTTPException(400, f"خطأ في قراءة الملف: {e}")

    global CURRENT_BINS
    with _lock:
        if mode == "append":
            CURRENT_BINS = _clean_bins(CURRENT_BINS + bins)
        else:
            CURRENT_BINS = bins
        _reset_cycle()
    return RedirectResponse("/", status_code=303)

@app.get("/health")
def health():
    return {"ok": True, "bins_count": len(CURRENT_BINS)}

@app.get("/generate", response_model=CardOut)
def generate():
    global _last_bin
    with _lock:
        if not CURRENT_BINS:
            return JSONResponse({"error":"ارفع BINs أولًا من /"}, status_code=400)
        # Round-robin لضمان BIN مختلف عن آخر ريكوست
        if _cycle is None:
            _reset_cycle()
        # خُد التالي، وتجنب تكرار آخر BIN إن أمكن
        b = next(_cycle)
        if _last_bin and len(CURRENT_BINS) > 1 and b == _last_bin:
            b = next(_cycle)
        _last_bin = b

    pan = gen_pan(b, infer_len(b))
    masked = pan[:6] + "******" + pan[-4:]
    return CardOut(pan=pan, masked=masked, bin_used=b)
