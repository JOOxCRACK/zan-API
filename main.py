from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
import itertools, threading, json, secrets, datetime

app = FastAPI(
    title="CC GEN PRV API @JOOxCRACK",
    description="BIN-based card generator",
    version="2.1.0"
)

# ===== In-memory store =====
CURRENT_BINS: list[str] = []
_lock = threading.Lock()
_cycle = None
_last_bin = None

# ===== Helpers (lengths, Luhn, etc.) =====
BIN_LEN_HINT = {
    "34": 15, "37": 15,           # Amex
    "4": 16,                      # Visa
    "51": 16, "52": 16, "53": 16, "54": 16, "55": 16,  # MC
    "2": 16, "6011": 16, "65": 16 # Simplified
}

def infer_len(b: str) -> int:
    for p in sorted(BIN_LEN_HINT.keys(), key=len, reverse=True):
        if b.startswith(p): return BIN_LEN_HINT[p]
    return 16

def luhn_check_digit(num_wo_check: str) -> str:
    digits = [int(d) for d in num_wo_check]
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9: d -= 9
        total += d
    return str((10 - (total % 10)) % 10)

def gen_pan_from_bin(bin_str: str, total_len: int) -> str:
    body_len = total_len - len(bin_str) - 1
    body = "".join(str(secrets.randbelow(10)) for _ in range(body_len))
    partial = bin_str + body
    return partial + luhn_check_digit(partial)

def cvv_len_for_bin(b: str) -> int:
    return 4 if b.startswith(("34", "37")) else 3

def gen_exp_and_cvv(b: str):
    now = datetime.datetime.utcnow()
    month = secrets.randbelow(12) + 1
    year = (now.year + secrets.choice([1,2,3,4,5])) % 100
    exp_m, exp_y = f"{month:02d}", f"{year:02d}"
    n = cvv_len_for_bin(b)
    cvv = "".join(str(secrets.randbelow(10)) for _ in range(n))
    return exp_m, exp_y, cvv

def gen_one_line(b: str) -> str:
    pan = gen_pan_from_bin(b, infer_len(b))
    exp_m, exp_y, cvv = gen_exp_and_cvv(b)
    return f"{pan}|{exp_m}|{exp_y}|{cvv}"

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

# ===== Single UI (upload + download controls) =====
@app.get("/", response_class=HTMLResponse)
def index():
    count = len(CURRENT_BINS)
    return f"""
<!doctype html>
<html><head><meta charset="utf-8"><title>CC GEN PRV API @JOOxCRACK</title>
<style>
 body{{font-family:Arial,Helvetica,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;justify-content:center}}
 .wrap{{max-width:480px;margin:24px;padding:0 8px;width:100%}}
 h1{{color:#58a6ff;margin:0 0 12px}}
 .card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px;margin:12px 0}}
 label{display:block;margin:6px 0}
 input,select,button{{width:100%;padding:10px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9}}
 button{{background:#238636;color:#fff;border:none;cursor:pointer;margin-top:10px}}
 button:hover{{background:#2ea043}}
 .row{{display:flex;gap:10px}}
 .muted{{opacity:.8}}
</style></head>
<body><div class="wrap">
  <h1>CC GEN PRV API @JOOxCRACK</h1>

  <div class="card">
    <p class="muted">Loaded BINs: <b>{count}</b></p>
    <form action="/upload" method="post" enctype="multipart/form-data">
      <label>Upload BIN file (JSON array, or TXT: one BIN per line)</label>
      <input type="file" name="file" required>
      <div class="row">
        <select name="mode" style="flex:1">
          <option value="replace">Replace</option>
          <option value="append">Append</option>
        </select>
        <button type="submit" style="flex:1">Upload</button>
      </div>
    </form>
  </div>

  <div class="card">
    <form action="/bulk" method="get">
      <label>Cards per BIN</label>
      <input type="number" name="per_bin" value="1000" min="1" required>
      <label>Shuffle all cards</label>
      <select name="shuffle">
        <option value="true" selected>True</option>
        <option value="false">False</option>
      </select>
      <button type="submit">Generate & Download (TXT)</button>
    </form>
  </div>

</div></body></html>
"""

# ===== Upload & Health =====
@app.post("/upload")
async def upload_bins(file: UploadFile = File(...), mode: str = Form("replace")):
    content = await file.read()
    name = (file.filename or "").lower()
    try:
        if name.endswith(".json"):
            data = json.loads(content.decode("utf-8"))
            if not isinstance(data, list): raise ValueError("JSON must be array.")
            bins = data
        else:
            text = content.decode("utf-8", errors="ignore")
            bins = [line.strip() for line in text.splitlines()]
        bins = _clean_bins(bins)
        if not bins: raise ValueError("No valid BINs.")
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

# ===== Bulk download (TXT) =====
@app.get("/bulk")
def bulk(per_bin: int = 1000, shuffle: str = "true"):
    with _lock:
        bins = CURRENT_BINS.copy()
    if not bins:
        return Response("Upload BINs first", status_code=400, media_type="text/plain")

    lines: list[str] = []
    for b in bins:
        seen = set()
        while len(seen) < per_bin:
            line = gen_one_line(b)              # "CARD|MM|YY|CVV"
            pan = line.split("|", 1)[0]
            if pan in seen:                      # avoid duplicate PANs per BIN
                continue
            seen.add(pan)
            lines.append(line)

    do_shuffle = str(shuffle).lower() in ("1", "true", "yes", "on")
    if do_shuffle and len(lines) > 1:
        shuffle_inplace(lines)

    content = "\n".join(lines) + "\n"
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"cards_{len(bins)}bins_{per_bin}per_{'shuf_' if do_shuffle else ''}{ts}.txt"
    return Response(
        content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
