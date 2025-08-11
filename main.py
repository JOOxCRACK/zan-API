from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response
import itertools, threading, json, secrets, datetime

app = FastAPI(
    title="CC GEN PRV API @JOOxCRACK",
    description="BIN-based credit card generator (algorithmic valid with realistic constraints)",
    version="2.0.0"
)

# ==== In-memory BIN store ====
CURRENT_BINS: list[str] = []
_lock = threading.Lock()
_cycle = None
_last_bin = None

# ==== Brand length hints ====
BIN_LEN_HINT = {
    "34": 15, "37": 15,            # Amex
    "4": 16,                       # Visa
    "51": 16, "52": 16, "53": 16, "54": 16, "55": 16,  # MC
    "2": 16, "6011": 16, "65": 16  # Others (simplified)
}

# ---------- Luhn ----------
def luhn_check_digit(num_wo_check: str) -> str:
    digits = [int(d) for d in num_wo_check]
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - (total % 10)) % 10)

def infer_len(b: str) -> int:
    for p in sorted(BIN_LEN_HINT.keys(), key=len, reverse=True):
        if b.startswith(p):
            return BIN_LEN_HINT[p]
    return 16

# ---------- “Realistic” body constraints ----------
BAD_BLOCKS = {"0000", "1234", "1111"}

def has_long_repeat(s: str, k: int = 4) -> bool:
    # ≥k نفس الرقم متتالي
    run = 1
    for i in range(1, len(s)):
        run = run + 1 if s[i] == s[i-1] else 1
        if run >= k:
            return True
    return False

def is_seq_chunk(chunk: str) -> bool:
    # تصاعدي أو تنازلي بطول ≥4
    if len(chunk) < 4:
        return False
    inc = all((int(chunk[i+1]) - int(chunk[i]) == 1) for i in range(len(chunk)-1))
    dec = all((int(chunk[i]) - int(chunk[i+1]) == 1) for i in range(len(chunk)-1))
    return inc or dec

def has_long_sequence(s: str, k: int = 5) -> bool:
    # أي نافذة طول k متسلسلة
    if len(s) < k:
        return False
    for i in range(len(s)-k+1):
        if is_seq_chunk(s[i:i+k]):
            return True
    return False

def body_is_plausible(body: str) -> bool:
    # منع بلوكات سيئة في آخر 8 أرقام
    tail = body[-8:] if len(body) >= 8 else body
    for i in range(0, max(0, len(tail)-3)):
        if tail[i:i+4] in BAD_BLOCKS:
            return False
    # أول رقم في الجسم لا يكون 0
    if body and body[0] == "0":
        return False
    # آخر 4 مش كلهم أصفار
    if len(body) >= 4 and body[-4:] == "0000":
        return False
    # تكرارات طويلة وتسلسلات طويلة
    if has_long_repeat(body, 4):
        return False
    if has_long_sequence(body, 5):
        return False
    return True

def gen_body_plausible(length: int) -> str:
    # توليد حتى يطابق القيود (محاولات محدودة)
    for _ in range(1000):  # سقف أمان
        s = "".join(str(secrets.randbelow(10)) for _ in range(length))
        if body_is_plausible(s):
            return s
    # fallback لو القيود قاسية جدًا
    return "".join(str(secrets.randbelow(10)) for _ in range(length))

def gen_pan_from_bin(bin_str: str, total_len: int) -> str:
    body_len = total_len - len(bin_str) - 1
    body = gen_body_plausible(body_len)
    partial = bin_str + body
    return partial + luhn_check_digit(partial)

# ---------- Exp / CVV ----------
def cvv_len_for_bin(b: str) -> int:
    return 4 if b.startswith(("34", "37")) else 3

def gen_exp_and_cvv(b: str):
    now = datetime.datetime.utcnow()
    month = secrets.randbelow(12) + 1
    year = (now.year + secrets.choice([1, 2, 3, 4, 5])) % 100
    exp_m, exp_y = f"{month:02d}", f"{year:02d}"
    n = cvv_len_for_bin(b)
    cvv = "".join(str(secrets.randbelow(10)) for _ in range(n))
    return exp_m, exp_y, cvv

def gen_one_line(b: str) -> str:
    pan = gen_pan_from_bin(b, infer_len(b))
    exp_m, exp_y, cvv = gen_exp_and_cvv(b)
    return f"{pan}|{exp_m}|{exp_y}|{cvv}"

# ---------- Utils ----------
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

def shuffle_inplace(lines: list[str]) -> None:
    for i in range(len(lines) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        lines[i], lines[j] = lines[j], lines[i]

# ================= UI =================
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
  .card {{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px;width:360px;margin-bottom:16px}}
  input,select,button {{width:100%;margin-top:10px;padding:10px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9}}
  button {{background:#238636;color:#fff;border:none;cursor:pointer}}
  button:hover {{background:#2ea043}}
  .row {{display:flex;gap:10px}}
  a {{text-decoration:none}}
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
  </div>

  <div class="card">
    <p>Quick actions</p>
    <div class="row">
      <a href="/generate" style="flex:1"><button type="button" style="width:100%">Random Generate (1)</button></a>
      <a href="/health" style="flex:1"><button type="button" style="width:100%">Health</button></a>
    </div>
    <form action="/bulk" method="get" style="margin-top:10px">
      <label>Bulk per BIN</label>
      <input type="number" name="per_bin" value="1000" min="1">
      <label>Shuffle</label>
      <select name="shuffle">
        <option value="true" selected>True</option>
        <option value="false">False</option>
      </select>
      <button type="submit">Generate & Download (TXT)</button>
    </form>
  </div>
</body>
</html>
"""

# =============== Upload / Health ===============
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

# =============== One-by-one ===============
@app.get("/generate", response_class=PlainTextResponse)
def generate():
    """One card per request; rotates BINs to avoid consecutive duplicates."""
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
    return gen_one_line(b)

# =============== Bulk (all uploaded BINs) ===============
@app.get("/bulk")
def bulk(per_bin: int = 1000, shuffle: str = "true"):
    """Generate <per_bin> cards per uploaded BIN and download as a single TXT file."""
    with _lock:
        bins = CURRENT_BINS.copy()
    if not bins:
        return Response("Upload BINs first", status_code=400, media_type="text/plain")

    lines: list[str] = []
    for b in bins:
        seen = set()
        while len(seen) < per_bin:
            line = gen_one_line(b)
            pan = line.split("|", 1)[0]
            if pan in seen:  # avoid dup PANs per BIN
                continue
            seen.add(pan)
            lines.append(line)

    do_shuffle = str(shuffle).lower() in ("1", "true", "yes", "on")
    if do_shuffle and len(lines) > 1:
        shuffle_inplace(lines)

    content = "\n".join(lines) + "\n"
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"cards_{len(bins)}bins_{per_bin}per_{'shuf_' if do_shuffle else ''}{ts}.txt"
    return Response(content, media_type="text/plain",
                    headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'})

# =============== Bulk one BIN directly ===============
@app.get("/bulk_one")
def bulk_one(bin: str = Query(..., min_length=5, max_length=12), count: int = 1000, shuffle: str = "true"):
    """Generate <count> cards for a single BIN (no need to upload file)."""
    b = "".join(ch for ch in bin if ch.isdigit())
    if not (5 <= len(b) <= 12):
        return Response("Invalid BIN", status_code=400, media_type="text/plain")

    lines = []
    seen = set()
    while len(seen) < count:
        line = gen_one_line(b)
        pan = line.split("|", 1)[0]
        if pan in seen:
            continue
        seen.add(pan)
        lines.append(line)

    if str(shuffle).lower() in ("1", "true", "yes", "on") and len(lines) > 1:
        shuffle_inplace(lines)

    content = "\n".join(lines) + "\n"
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"cards_{b}_{count}_{ts}.txt"
    return Response(content, media_type="text/plain",
                    headers={"Content-Disposition": f'attachment; filename=\"{filename}\""})
