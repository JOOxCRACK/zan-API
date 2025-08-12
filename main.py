from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from datetime import datetime
import io, secrets

app = FastAPI(
    title="CC GEN PRV API @JOOxCRACK",
    description="Like the Tkinter script: upload BINs file, choose count, download TXT",
    version="3.1.0"
)

# ===== Brand hints (length & cvv) =====
BIN_LEN_HINT = {
    "34": 15, "37": 15,      # AMEX
    "4": 16,                 # Visa
    "51": 16, "52": 16, "53": 16, "54": 16, "55": 16,  # MasterCard classic
    "2": 16, "6011": 16, "65": 16                      # simplified others
}

def infer_len(bin_str: str) -> int:
    for p in sorted(BIN_LEN_HINT.keys(), key=len, reverse=True):
        if bin_str.startswith(p):
            return BIN_LEN_HINT[p]
    return 16

def cvv_len_for_bin(bin_str: str) -> int:
    return 4 if bin_str.startswith(("34", "37")) else 3

# ===== Luhn =====
def luhn_checksum(card_number: str) -> int:
    digits = [int(d) for d in card_number]
    odd = digits[-1::-2]
    even = digits[-2::-2]
    checksum = sum(odd)
    for d in even:
        d2 = d * 2
        checksum += d2 if d2 < 10 else (d2 - 9)
    return checksum % 10

def generate_luhn(bin_input: str) -> str:
    # زي سكربتك، بس بنظبط الطول حسب البراند (AMEX=15، غيره=16)
    total_len = infer_len(bin_input)
    if len(bin_input) >= total_len:
        raise ValueError(f"BIN '{bin_input}' too long for target length {total_len}")
    body_len = total_len - len(bin_input) - 1
    body = "".join(str(secrets.randbelow(10)) for _ in range(body_len))
    partial = bin_input + body
    # رقم التحقق
    for d in range(10):
        if luhn_checksum(partial + str(d)) == 0:
            return partial + str(d)
    # نظريًا مش هنوصل هنا
    raise RuntimeError("Failed to compute Luhn check digit")

# ===== Generate one line (like your script) =====
def generate_card(bin_input: str) -> str:
    bin_input = "".join(ch for ch in bin_input if ch.isdigit())
    if not (5 <= len(bin_input) <= 12):
        raise ValueError("BIN must be 5–12 digits.")
    card_number = generate_luhn(bin_input)
    exp_month = f"{secrets.randbelow(12) + 1:02d}"
    # YY فقط (زي الشكل اللي كنت طالبه)
    year_yy = (datetime.utcnow().year + secrets.choice([1,2,3,4,5])) % 100
    exp_year = f"{year_yy:02d}"
    # AMEX 4 أرقام، غيره 3 أرقام
    n_cvv = cvv_len_for_bin(bin_input)
    low = 10**(n_cvv - 1)
    high = (10**n_cvv) - 1
    cvv = str(secrets.randbelow(high - low + 1) + low)
    return f"{card_number}|{exp_month}|{exp_year}|{cvv}"

def clean_bins_from_txt(text: str):
    out = []
    for line in text.splitlines():
        digits = "".join(ch for ch in line.strip() if ch.isdigit())
        if digits and 5 <= len(digits) <= 12 and digits not in out:
            out.append(digits)
    return out

# ===== UI: نفس فكرة "اختار ملف + دخل العدد + زرار" =====
@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>CC GEN PRV API @JOOxCRACK</title>
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
  </style>
</head>
<body>
  <div class="wrap">
    <h1>CC GEN PRV API @JOOxCRACK</h1>
    <div class="card">
      <form action="/generate" enctype="multipart/form-data" method="post">
        <label>Upload BINs file (TXT - one BIN per line)</label>
        <input type="file" name="file" accept=".txt" required>
        <label>Cards per BIN</label>
        <input type="number" name="count" value="1000" min="1" required>
        <button type="submit">Generate & Download (TXT)</button>
        <p class="muted">Format: <code>CARD|MM|YY|CVV</code> • AMEX=15 digits & CVV=4</p>
      </form>
    </div>
  </div>
</body>
</html>
"""

# ===== Generate & download (exactly like your flow) =====
@app.post("/generate")
async def generate(file: UploadFile = File(...), count: int = Form(...)):
    if not file.filename.lower().endswith(".txt"):
        raise HTTPException(400, "Please upload a .txt file (one BIN per line).")

    raw = await file.read()
    try:
        bins = clean_bins_from_txt(raw.decode("utf-8", errors="ignore"))
    except Exception as e:
        raise HTTPException(400, f"File parse error: {e}")

    if not bins:
        raise HTTPException(400, "No valid BINs in file (expect 5–12 digits each).")

    lines = []
    for b in bins:
        seen = set()
        to_make = count
        while to_make > 0:
            try:
                line = generate_card(b)  # CARD|MM|YY|CVV
            except ValueError:
                break  # BIN طويل زيادة بالنسبة للطول النهائي
            pan = line.split("|", 1)[0]
            if pan in seen:
                continue
            seen.add(pan)
            lines.append(line)
            to_make -= 1

    if not lines:
        raise HTTPException(400, "All BINs were invalid for their target lengths.")

    # Shuffle (زي ما طلبت: يتلخبطوا كلهم مع بعض)
    for i in range(len(lines) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        lines[i], lines[j] = lines[j], lines[i]

    buf = io.StringIO("\n".join(lines) + "\n")
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"cards_{len(bins)}bins_{count}per_{ts}.txt"
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from datetime import datetime
import io, secrets

app = FastAPI(
    title="CC GEN PRV API @JOOxCRACK",
    description="Like the Tkinter script: upload BINs file, choose count, download TXT",
    version="3.1.0"
)

# ===== Brand hints (length & cvv) =====
BIN_LEN_HINT = {
    "34": 15, "37": 15,      # AMEX
    "4": 16,                 # Visa
    "51": 16, "52": 16, "53": 16, "54": 16, "55": 16,  # MasterCard classic
    "2": 16, "6011": 16, "65": 16                      # simplified others
}

def infer_len(bin_str: str) -> int:
    for p in sorted(BIN_LEN_HINT.keys(), key=len, reverse=True):
        if bin_str.startswith(p):
            return BIN_LEN_HINT[p]
    return 16

def cvv_len_for_bin(bin_str: str) -> int:
    return 4 if bin_str.startswith(("34", "37")) else 3

# ===== Luhn =====
def luhn_checksum(card_number: str) -> int:
    digits = [int(d) for d in card_number]
    odd = digits[-1::-2]
    even = digits[-2::-2]
    checksum = sum(odd)
    for d in even:
        d2 = d * 2
        checksum += d2 if d2 < 10 else (d2 - 9)
    return checksum % 10

def generate_luhn(bin_input: str) -> str:
    # زي سكربتك، بس بنظبط الطول حسب البراند (AMEX=15، غيره=16)
    total_len = infer_len(bin_input)
    if len(bin_input) >= total_len:
        raise ValueError(f"BIN '{bin_input}' too long for target length {total_len}")
    body_len = total_len - len(bin_input) - 1
    body = "".join(str(secrets.randbelow(10)) for _ in range(body_len))
    partial = bin_input + body
    # رقم التحقق
    for d in range(10):
        if luhn_checksum(partial + str(d)) == 0:
            return partial + str(d)
    # نظريًا مش هنوصل هنا
    raise RuntimeError("Failed to compute Luhn check digit")

# ===== Generate one line (like your script) =====
def generate_card(bin_input: str) -> str:
    bin_input = "".join(ch for ch in bin_input if ch.isdigit())
    if not (5 <= len(bin_input) <= 12):
        raise ValueError("BIN must be 5–12 digits.")
    card_number = generate_luhn(bin_input)
    exp_month = f"{secrets.randbelow(12) + 1:02d}"
    # YY فقط (زي الشكل اللي كنت طالبه)
    year_yy = (datetime.utcnow().year + secrets.choice([1,2,3,4,5])) % 100
    exp_year = f"{year_yy:02d}"
    # AMEX 4 أرقام، غيره 3 أرقام
    n_cvv = cvv_len_for_bin(bin_input)
    low = 10**(n_cvv - 1)
    high = (10**n_cvv) - 1
    cvv = str(secrets.randbelow(high - low + 1) + low)
    return f"{card_number}|{exp_month}|{exp_year}|{cvv}"

def clean_bins_from_txt(text: str):
    out = []
    for line in text.splitlines():
        digits = "".join(ch for ch in line.strip() if ch.isdigit())
        if digits and 5 <= len(digits) <= 12 and digits not in out:
            out.append(digits)
    return out

# ===== UI: نفس فكرة "اختار ملف + دخل العدد + زرار" =====
@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>CC GEN PRV API @JOOxCRACK</title>
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
  </style>
</head>
<body>
  <div class="wrap">
    <h1>CC GEN PRV API @JOOxCRACK</h1>
    <div class="card">
      <form action="/generate" enctype="multipart/form-data" method="post">
        <label>Upload BINs file (TXT - one BIN per line)</label>
        <input type="file" name="file" accept=".txt" required>
        <label>Cards per BIN</label>
        <input type="number" name="count" value="1000" min="1" required>
        <button type="submit">Generate & Download (TXT)</button>
        <p class="muted">Format: <code>CARD|MM|YY|CVV</code> • AMEX=15 digits & CVV=4</p>
      </form>
    </div>
  </div>
</body>
</html>
"""

# ===== Generate & download (exactly like your flow) =====
@app.post("/generate")
async def generate(file: UploadFile = File(...), count: int = Form(...)):
    if not file.filename.lower().endswith(".txt"):
        raise HTTPException(400, "Please upload a .txt file (one BIN per line).")

    raw = await file.read()
    try:
        bins = clean_bins_from_txt(raw.decode("utf-8", errors="ignore"))
    except Exception as e:
        raise HTTPException(400, f"File parse error: {e}")

    if not bins:
        raise HTTPException(400, "No valid BINs in file (expect 5–12 digits each).")

    lines = []
    for b in bins:
        seen = set()
        to_make = count
        while to_make > 0:
            try:
                line = generate_card(b)  # CARD|MM|YY|CVV
            except ValueError:
                break  # BIN طويل زيادة بالنسبة للطول النهائي
            pan = line.split("|", 1)[0]
            if pan in seen:
                continue
            seen.add(pan)
            lines.append(line)
            to_make -= 1

    if not lines:
        raise HTTPException(400, "All BINs were invalid for their target lengths.")

    # Shuffle (زي ما طلبت: يتلخبطوا كلهم مع بعض)
    for i in range(len(lines) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        lines[i], lines[j] = lines[j], lines[i]

    buf = io.StringIO("\n".join(lines) + "\n")
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"cards_{len(bins)}bins_{count}per_{ts}.txt"
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode()),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
