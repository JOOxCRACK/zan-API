from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
import secrets, datetime, io, json

app = FastAPI(
    title="CC GEN PRV API @JOOxCRACK",
    description="BIN-based card generator (Luhn-valid with tuned AMEX/body constraints)",
    version="2.3.0"
)

# ===== Brand length hints =====
BIN_LEN_HINT = {
    "34": 15, "37": 15,      # AMEX
    "4": 16,                 # Visa
    "51": 16, "52": 16, "53": 16, "54": 16, "55": 16,  # MC classic
    "2": 16, "6011": 16, "65": 16                      # simplified others
}

def infer_len(bin_str: str) -> int:
    for p in sorted(BIN_LEN_HINT.keys(), key=len, reverse=True):
        if bin_str.startswith(p):
            return BIN_LEN_HINT[p]
    return 16

def cvv_len_for_bin(bin_str: str) -> int:
    return 4 if bin_str.startswith(("34","37")) else 3  # AMEX=4

# ===== Luhn =====
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

# ===== “Realistic” body constraints =====
BAD_TRIPLES = {"000", "123", "111", "222", "333", "444", "555", "666", "777", "888", "999"}

def _has_repeat(s: str, k: int) -> bool:
    run = 1
    for i in range(1, len(s)):
        run = run + 1 if s[i] == s[i-1] else 1
        if run >= k:
            return True
    return False

def _has_sequence(s: str, k: int) -> bool:
    if len(s) < k: return False
    for i in range(len(s)-k+1):
        chunk = s[i:i+k]
        inc = all(int(chunk[j+1]) - int(chunk[j]) == 1 for j in range(k-1))
        dec = all(int(chunk[j]) - int(chunk[j+1]) == 1 for j in range(k-1))
        if inc or dec: return True
    return False

def _weighted_digit(nonzero_bias: bool = False) -> str:
    # قلّل احتمال 0 عشان الشكل مايبقاش "ميت"
    pool = "0123456789"
    weights = [1, 3, 3, 3, 3, 3, 3, 3, 3, 3]  # 0 وزن 1، باقي الأرقام وزن 3
    if nonzero_bias:
        weights[0] = 0  # أول رقم في الجسم مش صفر
    total = sum(weights)
    r = secrets.randbelow(total)
    acc = 0
    for d, w in zip(pool, weights):
        acc += w
        if r < acc:
            return d
    return "0"

def _gen_amex_body(body_len: int) -> str:
    # جسم AMEX مقيَّد عشان يطلع شكل “حي”
    tries = 0
    while tries < 2000:
        tries += 1
        digits = []
        for pos in range(body_len):
            d = _weighted_digit(nonzero_bias=(pos == 0))
            if pos >= 2 and d == digits[-1] == digits[-2]:
                # امنع 3 متتالي أثناء البناء
                for _ in range(10):
                    d2 = _weighted_digit()
                    if d2 != d:
                        d = d2; break
            digits.append(d)
        s = "".join(digits)
        if s[0] == "0": 
            continue
        if _has_repeat(s, 3): 
            continue
        if _has_sequence(s, 4): 
            continue
        tail = s[-6:] if len(s) >= 6 else s
        bad = False
        for i in range(0, max(0, len(tail)-2)):
            if tail[i:i+3] in BAD_TRIPLES:
                bad = True; break
        if bad:
            continue
        return s
    # fallback نادر
    return "".join(_weighted_digit(nonzero_bias=(i == 0)) for i in range(body_len))

def gen_pan_from_bin(bin_str: str, total_len: int) -> str:
    if len(bin_str) >= total_len:
        # BIN أطول من الطول النهائي (مثلاً AMEX=15)
        raise ValueError(f"BIN '{bin_str}' too long for length {total_len}")
    body_len = total_len - len(bin_str) - 1

    if bin_str.startswith(("34", "37")) and total_len == 15:
        body = _gen_amex_body(body_len)
    else:
        # باقي البراندات بقيود أخف
        tries = 0
        while True:
            tries += 1
            body = "".join(_weighted_digit(nonzero_bias=(i == 0)) for i in range(body_len))
            if body[0] == "0":
                continue
            if _has_repeat(body, 4):
                continue
            if _has_sequence(body, 5):
                continue
            break
            if tries > 2000:
                break

    partial = bin_str + body
    return partial + luhn_check_digit(partial)

def gen_exp_and_cvv(bin_str: str):
    now = datetime.datetime.utcnow()
    month = secrets.randbelow(12) + 1
    year_yy = (now.year + secrets.choice([1,2,3,4,5])) % 100  # YY
    exp_m, exp_y = f"{month:02d}", f"{year_yy:02d}"
    n = cvv_len_for_bin(bin_str)
    cvv = "".join(str(secrets.randbelow(10)) for _ in range(n))
    return exp_m, exp_y, cvv

def gen_one_line(bin_str: str) -> str:
    pan = gen_pan_from_bin(bin_str, infer_len(bin_str))
    m, y, cvv = gen_exp_and_cvv(bin_str)
    return f"{pan}|{m}|{y}|{cvv}"

# ===== BIN cleaning =====
def clean_bins(lines):
    out = []
    for b in lines or []:
        digits = "".join(ch for ch in str(b).strip() if ch.isdigit())
        # نقبل 5..12 فقط (BIN/IIN نموذجي)
        if digits and 5 <= len(digits) <= 12 and digits not in out:
            out.append(digits)
    return out

# ===== UI (single page) =====
@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!doctype html>
<html><head><meta charset="utf-8"><title>CC GEN PRV API @JOOxCRACK</title>
<style>
 body{{font-family:Arial,Helvetica,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;justify-content:center}}
 .wrap{{max-width:520px;margin:24px;padding:0 8px;width:100%}}
 h1{{color:#58a6ff;margin:0 0 12px}}
 .card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px;margin:12px 0}}
 label{{display:block;margin:6px 0}}
 input,button{{width:100%;padding:10px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9}}
 button{{background:#238636;color:#fff;border:none;cursor:pointer;margin-top:10px}}
 button:hover{{background:#2ea043}}
 .muted{{opacity:.8}}
</style></head>
<body><div class="wrap">
  <h1>CC GEN PRV API @JOOxCRACK</h1>
  <div class="card">
    <form action="/generate" enctype="multipart/form-data" method="post">
      <label>Upload BIN file (TXT or JSON array)</label>
      <input type="file" name="file" required>
      <label>Cards per BIN</label>
      <input type="number" name="count" value="1000" min="1" required>
      <button type="submit">Generate & Download (TXT)</button>
      <p class="muted">Format: <code>CARD|MM|YY|CVV</code> • AMEX = 15-digit PAN & 4-digit CVV</p>
    </form>
  </div>
</div></body></html>
"""

# ===== Generate & download =====
@app.post("/generate")
async def generate(file: UploadFile = File(...), count: int = Form(...)):
    raw = await file.read()
    name = (file.filename or "").lower()

    # Parse file (TXT or JSON array)
    try:
        if name.endswith(".json"):
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, list):
                raise ValueError("JSON must be an array of BIN strings.")
            bins = clean_bins(data)
        else:
            bins = clean_bins(raw.decode("utf-8", errors="ignore").splitlines())
    except Exception as e:
        raise HTTPException(400, f"File parse error: {e}")

    if not bins:
        raise HTTPException(400, "No valid BINs (expect 5–12 digits each).")

    lines = []
    for b in bins:
        seen = set()
        needed = count
        while needed > 0:
            try:
                line = gen_one_line(b)  # قد يرمي لو BIN أطول من الطول النهائي
            except ValueError:
                break  # BIN غير صالح لطوله بالنسبة للبراند (مثلاً AMEX)
            pan = line.split("|", 1)[0]
            if pan in seen:
                continue
            seen.add(pan)
            lines.append(line)
            needed -= 1

    if not lines:
        raise HTTPException(400, "All BINs were invalid for their target lengths.")

    # Shuffle (Fisher–Yates مع secrets)
    for i in range(len(lines) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        lines[i], lines[j] = lines[j], lines[i]

    buf = io.StringIO("\n".join(lines) + "\n")
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"cards_{len(bins)}bins_{count}per_{ts}.txt"
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
