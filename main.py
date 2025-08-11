# main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
import itertools, threading, json, secrets

app = FastAPI(title="BIN-based Test Card API", version="1.3.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

CURRENT_BINS: List[str] = []  # انت هترفع بيناتك

BIN_LEN_HINT = {"34":15,"37":15,"4":16,"51":16,"52":16,"53":16,"54":16,"55":16,"2":16,"6011":16,"65":16}

def infer_pan_length(bin_str: str) -> int:
    for p in sorted(BIN_LEN_HINT.keys(), key=len, reverse=True):
        if bin_str.startswith(p): return BIN_LEN_HINT[p]
    return 16

def luhn_check_digit(number_without_check: str) -> str:
    digits = [int(d) for d in number_without_check]
    total = 0; parity = (len(digits)) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9: d -= 9
        total += d
    return str((10 - (total % 10)) % 10)

def _rand_digit() -> str:
    return str(secrets.randbelow(10))  # 0..9

def generate_pan(bin_str: str, length: int) -> str:
    body_len = length - len(bin_str) - 1
    body = "".join(_rand_digit() for _ in range(body_len))
    partial = bin_str + body
    return partial + luhn_check_digit(partial)

def brand_from_bin(bin_str: str) -> str:
    if bin_str.startswith(("34","37")): return "AMEX (test)"
    if bin_str.startswith("4"): return "VISA (test)"
    if bin_str.startswith(tuple(str(i) for i in range(51,56))) or bin_str.startswith("2"): return "MASTERCARD (test)"
    if bin_str.startswith(("6011","65")): return "DISCOVER (test)"
    return "UNKNOWN (test)"

def _clean_bins(bins: List[str]) -> List[str]:
    cleaned = []
    for b in bins or []:
        b = "".join(ch for ch in b if ch.isdigit())
        if b and 5 <= len(b) <= 12 and b not in cleaned:
            cleaned.append(b)
    if not cleaned:
        raise HTTPException(400, "ارفع BINs صالحة (5–12 أرقام).")
    return cleaned

class GenerateRequest(BaseModel):
    bins: Optional[List[str]] = None     # لو None نستخدم CURRENT_BINS
    count: int = Field(1, ge=1, le=100)
    strategy: Literal["round_robin", "random_no_repeat"] = "round_robin"
    wrap_around: bool = True

class CardOut(BaseModel):
    pan: str
    masked: str
    bin_used: str
    brand_hint: str
    note: str = "TEST USE ONLY – Not valid for real transactions"

_rr_lock = threading.Lock()
_rr_cycle = itertools.cycle(CURRENT_BINS.copy())

@app.get("/health")
def health():
    return {"ok": True, "bins_count": len(CURRENT_BINS)}

@app.post("/generate", response_model=List[CardOut])
def generate(req: GenerateRequest):
    bins = _clean_bins(req.bins if req.bins is not None else CURRENT_BINS)
    if not bins:
        raise HTTPException(400, "ارفع BINs أولًا عبر الصفحة الرئيسية.")

    chosen_bins: List[str] = []
    if req.strategy == "round_robin":
        global _rr_cycle
        with _rr_lock:
            _rr_cycle = itertools.cycle(bins)
            for _ in range(req.count):
                chosen_bins.append(next(_rr_cycle))
    else:  # random_no_repeat
        if req.count <= len(bins):
            # اختيار بلا تكرار باستخدام secrets
            pool = bins[:]  # نسخ
            # خلط آمن
            for i in range(len(pool)-1, 0, -1):
                j = secrets.randbelow(i+1)
                pool[i], pool[j] = pool[j], pool[i]
            chosen_bins = pool[:req.count]
        else:
            if not req.wrap_around:
                raise HTTPException(400, "count أكبر من عدد الـBINs ولم يتم السماح بالـ wrap_around.")
            times = (req.count + len(bins) - 1) // len(bins)
            pool = (bins * times)[:req.count]
            # خلط آمن
            for i in range(len(pool)-1, 0, -1):
                j = secrets.randbelow(i+1)
                pool[i], pool[j] = pool[j], pool[i]
            # منع تكرار متتالي لنفس BIN قدر الإمكان
            fixed = [pool[0]]
            for b in pool[1:]:
                if b == fixed[-1]:
                    # ابحث عن موقع لتبديل آمن
                    for j in range(len(fixed)-1, -1, -1):
                        if fixed[j] != b:
                            fixed[j], b = b, fixed[j]
                            break
                fixed.append(b)
            chosen_bins = fixed

    out = []
    for b in chosen_bins:
        pan = generate_pan(b, infer_pan_length(b))
        masked = pan[:6] + "******" + pan[-4:]
        out.append(CardOut(pan=pan, masked=masked, bin_used=b, brand_hint=brand_from_bin(b)))
    return out

# ====== صفحة رفع الملف ======
@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request, "count": len(CURRENT_BINS)})

@app.post("/upload")
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
        bins = _clean_bins(bins)
    except Exception as e:
        raise HTTPException(400, f"خطأ في قراءة الملف: {e}")

    global CURRENT_BINS, _rr_cycle
    if mode == "append":
        CURRENT_BINS = _clean_bins(CURRENT_BINS + bins)
    else:
        CURRENT_BINS = bins
    with _rr_lock:
        _rr_cycle = itertools.cycle(CURRENT_BINS.copy())
    return RedirectResponse(url="/", status_code=303)
