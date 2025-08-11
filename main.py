from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response
import itertools, threading, json, secrets, datetime

from faker import Faker
fake = Faker()  # for exp & cvv

app = FastAPI(
    title="CC GEN PRV API @JOOxCRACK",
    description="BIN-based credit card generator",
    version="1.1.0"
)

CURRENT_BINS = []
_lock = threading.Lock()
_cycle = None
_last_bin = None

# Length hints (simple)
BIN_LEN_HINT = {
    "34": 15, "37": 15,           # Amex
    "4": 16,                       # Visa
    "51": 16, "52": 16, "53": 16, "54": 16, "55": 16,  # MC
    "2": 16, "6011": 16, "65": 16 # Others (simplified)
}

def infer_len(b: str) -> int:
    for p in sorted(BIN_LEN_HINT.keys(), key=len, reverse=True):
        if b.startswith(p):
            return BIN_LEN_HINT[p]
    return 16

def luhn_check_digit(num: str) -> str:
    digits = [int(d) for d in num]
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - (total % 10)) % 10)

def gen_pan_from_bin(bin_str: str, length: int) -> str:
    body_len = length - len(bin_str) - 1
    body = "".join(str(secrets.randbelow(10)) for _ in range(body_len))
    partial = bin_str + body
    return partial + luhn_check_digit(partial)

def cvv_len_for_bin(b: str) -> int:
    return 4 if b.startswith(("34", "37")) else 3

def gen_exp_and_cvv_via_faker(b: str):
    # exp with Faker: returns "MM|YY", split to pieces
    exp = fake.credit_card_expire(start="now", end="+5y", date_format="%m|%y")
    exp_m, exp_y = exp.split("|")
    # cvv from Faker (3 or 4 based on brand hint)
    n = cvv_len_for_bin(b)
    # faker.credit_card_security_code(card_type=None) -> 3 digits usually
    # نضمن الطول n:
    base = fake.credit_card_security_code()
    if len(base) < n:
        base = (base + "0"*n)[:n]
    elif len(base) > n:
        base = base[:n]
    return exp_m, exp_y, base

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
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>CC GEN PRV API @JOOxCRACK</title>
<style>
body {{font-family: Arial, sans-serif;background:#0d1117;color:#c9d1d9;display:flex;flex-direction:column;align-items:center;padding:24px}}
h1 {{color:#58a6ff;margin:0 0 16px}}
.card {{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px;width:340px}}
input,select,button {{width:100%;margin-top:10px;padding:10px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9}}
button {{background:#238636;color:#fff;border:none;cursor:pointer}}
button:hover {{background:#2ea043}}
.small {{opacity:.8;margin-top:10px}}
</style>
</head>
<body>
  <h1>CC GEN PRV API @JOOxCRACK</h1>
  <div class="card">
    <p>Loaded BINs: <b>{count}</b></p>
    <form action="/upload" method="post" enctype="multipart/form-data">
      <label>BIN file (JSON array or TXT: one BIN per line)</label>
      <input type="file" name="file" required>
      <label>Mode</label>
      <select name="mode">
        <option value="replace">Replace</option>
        <option value="append">Append</option>
      </select>
      <button type="submit">Upload</button>
    </form>
    <p class="small">Endpoints: <code>GET /generate</code> • <code>GET /bulk?per_bin=1000</code></p>
  </div>
</body>
</html>
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
    """One card per request, rotates BINs (no consecutive same BIN if possible)."""
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

    pan = gen_pan_from_bin(b, infer_len(b))
    exp_m, exp_y, cvv = gen_exp_and_cvv_via_faker(b)
    return f"{pan}|{exp_m}|{exp_y}|{cvv}"

def gen_one_line(b: str) -> str:
    pan = gen_pan_from_bin(b, infer_len(b))
    exp_m, exp_y, cvv = gen_exp_and_cvv_via_faker(b)
    return f"{pan}|{exp_m}|{exp_y}|{cvv}"

@app.get("/bulk")
def bulk(per_bin: int = 1000):
    """Generate <per_bin> cards per BIN and download as a single TXT file."""
    with _lock:
        bins = CURRENT_BINS.copy()
    if not bins:
        return Response("Upload BINs first", status_code=400, media_type="text/plain")

    lines = []
    for b in bins:
        seen = set()
        while len(seen) < per_bin:
            line = gen_one_line(b)
            pan = line.split("|", 1)[0]
            if pan in seen:
                continue
            seen.add(pan)
            lines.append(line)

    content = "\n".join(lines) + "\n"
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"cards_{len(bins)}bins_{per_bin}per_{ts}.txt"
    return Response(content, media_type="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


    pan = gen_card_number(b, infer_len(b))
    exp_m, exp_y, cvv = gen_exp_and_cvv(b)
    return f"{pan}|{exp_m}|{exp_y}|{cvv}"
