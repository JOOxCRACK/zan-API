from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import HTMLResponse, StreamingResponse
import random
from datetime import datetime
import io

app = FastAPI()

# خوارزمية Luhn للتأكد من صلاحية الكروت
def luhn_checksum(card_number):
    def digits_of(n):
        return [int(d) for d in str(n)]
    digits = digits_of(card_number)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(digits_of(d * 2))
    return checksum % 10

def generate_luhn(bin_input):
    while True:
        card = bin_input + ''.join(str(random.randint(0, 9)) for _ in range(15 - len(bin_input)))
        check_digit = [str(d) for d in range(10) if luhn_checksum(card + str(d)) == 0]
        if check_digit:
            return card + check_digit[0]

def generate_card(bin_input):
    card_number = generate_luhn(bin_input)
    exp_month = f"{random.randint(1, 12):02}"
    exp_year = str(random.randint(datetime.now().year + 1, datetime.now().year + 5))
    cvv = f"{random.randint(100, 999)}"
    return f"{card_number}|{exp_month}|{exp_year}|{cvv}"

@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <html>
    <head>
        <title>CC GEN PRV API @JOOxCRACK</title>
        <style>
            body{{font-family:Arial,Helvetica,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;justify-content:center}}
            .wrap{{max-width:480px;margin:24px;padding:0 8px;width:100%}}
            h1{{color:#58a6ff;margin:0 0 12px}}
            .card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px;margin:12px 0}}
            label{{display:block;margin:6px 0}}
            input,button{{width:100%;padding:10px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9}}
            button{{background:#238636;color:#fff;border:none;cursor:pointer;margin-top:10px}}
            button:hover{{background:#2ea043}}
        </style>
    </head>
    <body>
        <div class="wrap">
            <h1>CC GEN PRV API @JOOxCRACK</h1>
            <div class="card">
                <form action="/generate" enctype="multipart/form-data" method="post">
                    <label>Upload BIN file</label>
                    <input type="file" name="file" required>
                    <label>Cards per BIN</label>
                    <input type="number" name="count" value="10" min="1" required>
                    <button type="submit">Generate & Download</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.post("/generate")
async def generate(file: UploadFile = File(...), count: int = Form(...)):
    content = await file.read()
    bins = content.decode().splitlines()
    cards = []

    for bin_val in bins:
        bin_val = bin_val.strip()
        if not bin_val.isdigit() or len(bin_val) < 6:
            continue
        for _ in range(count):
            cards.append(generate_card(bin_val))

    # خلط الكروت بشكل عشوائي
    random.shuffle(cards)

    # إنشاء ملف للتحميل
    output = io.StringIO("\n".join(cards))
    filename = "cards.txt"
    return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/plain",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})
