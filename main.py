from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
import itertools, threading, json, secrets, datetime

app = FastAPI(
    title="CC GEN PRV API @JOOxCRACK",
    description="Test-only BIN-based credit card generator",
    version="1.0.0"
)

CURRENT_BINS = []
_lock = threading.Lock()
_cycle = None
_last_bin = None

BIN_LEN_HINT = {
    "34": 15, "37": 15,
    "4": 16,
    "51": 16, "52": 16, "53": 16, "54": 16, "55": 16,
    "2": 16, "6011": 16, "65": 16
}

def infer_len(b):
    for p in sorted(BIN_LEN_HINT.keys(), key=len, reverse=True):
        if b.startswith(p):
            return BIN_LEN_HINT[p]
    return 16

def luhn_check_digit(num):
    digits = [int(d) for d in num]
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - (total % 10)) % 10)

def gen_card_number(bin_str, length):
    body_len = length - len(bin_str) - 1
    body = "".join(str(secrets.randbelow(10)) for _ in range(body_len))
    partial = bin_str + body
    return partial + luhn_check_digit(partial)

def cvv_len_for_bin(b):
    return 4 if b.startswith(("34", "37")) else 3

def gen_exp_and_cvv(b):
    now = datetime.datetime.utcnow()
    add_years = secrets.choice([1, 2, 3, 4, 5])
    month = secrets.randbelow(12) + 1
    year = (now.year + add_years) % 100
    exp_m = f"{month:02d}"
    exp_y = f"{year:02d}"
    cvv = "".join(str(secrets.randbelow(10)) for _ in range(cvv_len_for_bin(b)))
    return exp_m, exp_y, cvv

def _clean_bins(bins):
    out = []
    for b in bins or []:
        b = "".join(ch for ch in b if ch.isdigit())
        if b and 5 <= len(b) <= 12 and b not in out:
            out.append(b)
    return out

def _reset_cycle():
    global _cycle
    _cycle = itertools.cycle(CURRENT_BINS) if CURRENT_BINS else None

@app.get("/", response_class=HTMLResponse)
def upload_page():
    count = len(CURRENT_BINS)
    return f"""
<!doctype html><meta charset="utf-8">
<title>CC GEN PRV API @JOOxCRACK</title>
<h1>CC GEN PRV API @JOOxCRACK</h1>
<p>Loaded: <b>{count}</b> BIN(s)</p>
<form action="/upload" method="post" enctype="multipart/form-data">
  <input type="file" name="file" required><br><br>
  <select name="mode">
    <option value="replace">Replace</option>
    <option value="append">Append</option>
  </select><br><br>
  <button type="submit">Upload</button>
</form>
<p>Generate: <code>GET /generate</code> → returns: CARD|MM|YY|CVV</p>
"""

@app.post("/upload")
async def upload_bins(file: UploadFile = File(...), mode: str = Form("replace")):
    content = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".json"):
            data = json.loads(content.decode("utf-8"))
            if not isinstance(data, list):
                raise ValueError("JSON must be array.")
            bins = data
        else:
            text = content.decode("utf-8", errors="ignore")
            bins = [line.strip() for line in text.splitlines()]
        bins = _clean_bins(bins)
        if not bins:
            raise ValueError("No valid BINs.")
    except Exception as e:
        raise HTTPException(400, f"File parse error: {e}")

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

@app.get("/generate", response_class=PlainTextResponse)
def generate():
    global _last_bin
    with _lock:
        if not CURRENT_BINS:
            return PlainTextResponse("Upload BINs first", status_code=400)
        if _cycle is None:
            _reset_cycle()
        b = next(_cycle)
        if _last_bin and len(CURRENT_BINS) > 1 and b == _last_bin:
            b = next(_cycle)
        _last_bin = b

    pan = gen_card_number(b, infer_len(b))
    exp_m, exp_y, cvv = gen_exp_and_cvv(b)
    return f"{pan}|{exp_m}|{exp_y}|{cvv}"
