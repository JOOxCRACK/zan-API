from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import PlainTextResponse, FileResponse, HTMLResponse
import random
from datetime import datetime
import os
import uuid

app = FastAPI()

# ملف لحفظ البينات المرفوعة
BINS_FILE = "bins.txt"

# خوارزمية Luhn
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
    exp_year = f"{random.randint(datetime.now().year + 1, datetime.now().year + 5)}"
    cvv = f"{random.randint(100, 999)}"
    return f"{card_number}|{exp_month}|{exp_year}|{cvv}"

@app.get("/", response_class=HTMLResponse)
async def upload_page():
    return """
    <html>
        <head><title>CC GEN PRV API @JOOxCRACK</title></head>
        <body style="text-align:center; font-family:Arial;">
            <h2>Upload BINs File</h2>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="file" accept=".txt" required>
                <button type="submit">Upload</button>
            </form>
        </body>
    </html>
    """

@app.post("/upload")
async def upload_file(file: UploadFile):
    content = await file.read()
    with open(BINS_FILE, "wb") as f:
        f.write(content)
    return PlainTextResponse(f"BINS file uploaded: {file.filename}")

@app.get("/gen", response_class=PlainTextResponse)
async def gen_card():
    if not os.path.exists(BINS_FILE):
        return PlainTextResponse("No BINs uploaded", status_code=400)

    with open(BINS_FILE, "r") as f:
        bins = [line.strip() for line in f if line.strip()]

    if not bins:
        return PlainTextResponse("BINs file is empty", status_code=400)

    bin_input = random.choice(bins)
    return generate_card(bin_input)

@app.get("/bulk")
async def bulk_generate():
    if not os.path.exists(BINS_FILE):
        return PlainTextResponse("No BINs uploaded", status_code=400)

    with open(BINS_FILE, "r") as f:
        bins = [line.strip() for line in f if line.strip()]

    if not bins:
        return PlainTextResponse("BINs file is empty", status_code=400)

    all_cards = []
    for bin_input in bins:
        for _ in range(1000):
            all_cards.append(generate_card(bin_input))

    random.shuffle(all_cards)

    filename = f"cards_{uuid.uuid4().hex}.txt"
    with open(filename, "w") as f:
        f.write("\n".join(all_cards))

    return FileResponse(filename, media_type='text/plain', filename=filename, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

