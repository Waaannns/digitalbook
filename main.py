from fastapi import FastAPI, Request, Form, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates
import httpx, time, asyncio, base64, pymysql
from datetime import datetime
from PIL import Image
from io import BytesIO

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="awan_ganteng")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

GUTENDEX_API = "https://gutendex.com/books/"
QRIS_API = "https://kasir.orderkuota.com/qris/curl/create_qris_image.php?merchant=OK1559465&nominal=1000"
PRIVATE_MERCHANT = "OK1559465"

# @app.get("/", response_class=HTMLResponse)
# async def read_root(request: Request, search: str = None):
#     params = {"search": search} if search else {}
#     async with httpx.AsyncClient() as client:
#         response = await client.get(GUTENDEX_API, params=params)
#         data = response.json()
        
#         books = data.get("results", [])
#         next = data.get("next", [])
#         return templates.TemplateResponse("index.html", {
#             "request": request,
#             "books": books,
#             "search": search
#         })
    
    # response = r.get(GUTENDEX_API, params=params)
    # data = response.json()
    
    # books = data.get("results", [])
    # return templates.TemplateResponse("index.html", {
    #     "request": request,
    #     "books": books,
    #     "search": search
    # })

# Koneksi ke database MySQL
# def get_db_connection():
#     return pymysql.connect(
#         host="localhost",
#         user="root",
#         password="",
#         database="buku",
#         cursorclass=pymysql.cursors.DictCursor
#     )

def format_idr(value: int):
    return f"{value:,.0f}".replace(",", ".")

def get_timestamp():
    return int(time.time() * 1000)

@app.get("/404", response_class=HTMLResponse)
async def not_found_page(request: Request):
    return templates.TemplateResponse("404.html", {"request": request})

@app.get("/500")
async def internal_error_page(request: Request):
    return templates.TemplateResponse("500.html", {"request": request})

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, page: int = 1, search: str = None):
    params = {"page": page}
    if search:
        params["search"] = search

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(GUTENDEX_API, params=params)
            if response.status_code == 200:
                data = response.json()

                books = data.get("results", [])
                count = data.get("count", 0)

                total_pages = (count // 32) + (1 if count % 32 > 0 else 0)

                return templates.TemplateResponse("index.html", {
                    "request": request,
                    "books": books,
                    "search": search,
                    "page": page,
                    "total_pages": total_pages,
                })
    except httpx.ReadTimeout:
        return RedirectResponse("/500")

@app.get("/read/{book_id}")
async def baca_buku(request: Request, book_id: int):
    async with httpx.AsyncClient() as client:
        url = f"https://gutendex.com/books/{book_id}/"
        response = await client.get(url)
        if response.status_code == 200:
            data = response.json()
            html_url = data["formats"].get("text/html") or \
                        data["formats"].get("text/html; charset=utf-8")
            if html_url:
                return templates.TemplateResponse("read.html", {
                    "request": request,
                    "judul": data["title"],
                    "link_baca": html_url
                })

    return RedirectResponse("/404")

@app.get("/details/{book_id}")
async def baca_buku(request: Request, book_id: int):
    async with httpx.AsyncClient() as client:
        url = f"https://gutendex.com/books/{book_id}/"
        response = await client.get(url)
        if response.status_code == 200:
            books = response.json()

            return templates.TemplateResponse("detail.html", {
                "request": request,
                "books": books
            })
    return RedirectResponse("/404")

@app.get("/qris")
async def get_qris():
    async with httpx.AsyncClient() as client:
        r = await client.get(QRIS_API)
    return HTMLResponse(content=r.content, media_type="image/png")

@app.get("/buy/{book_id}", response_class=HTMLResponse)
async def show_payment(request: Request, book_id: int):
    async with httpx.AsyncClient() as client:
        url = f"https://gutendex.com/books/{book_id}/"
        response = await client.get(url)
        if response.status_code == 200:
            books = response.json()
            # Data contoh (bisa kamu ambil dari DB nanti)
            jumlah = 1
            harga = 1
            pajak_persen = 0.7
            pajak = int(harga * pajak_persen / 100)
            total_bayar = harga + pajak
            tanggal = datetime.now().strftime("%Y-%m-%d")
            barcode_img = await get_qris_image(harga)
            encoded_img = base64.b64encode(barcode_img.getvalue()).decode("utf-8")

            request.session["harga"] = harga
            request.session["tanggal"] = tanggal
            request.session["pajak"] = pajak
            request.session["total_bayar"] = total_bayar

            return templates.TemplateResponse("buy.html", {
                "request": request,
                "books": books,
                "harga": harga,
                "jumlah": jumlah,
                "tanggal": tanggal,
                "pajak_persen": pajak_persen,
                "pajak": pajak,
                "total_bayar": total_bayar,
                "encoded_img": encoded_img
            })

async def check_payment_status(merchant: str, nominal: int):
    timestamp = get_timestamp()
    url = f"https://kasir.orderkuota.com/qris/curl/status_pembayaran.php?timestamp={timestamp}&merchant={merchant}&nominal={nominal}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            return response.json()
        except Exception as e:
            return {"status": "error", "detail": str(e)}

async def get_qris_image(nominal: int):
    url = f"https://kasir.orderkuota.com/qris/curl/create_qris_image.php?merchant={PRIVATE_MERCHANT}&nominal={nominal}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        img = Image.open(BytesIO(response.content))
        barcode_area = img.crop((95, 315, 616, 836))
        output = BytesIO()
        barcode_area.save(output, format="PNG")
        output.seek(0)
        return output

@app.get("/status/{nominal}")
async def cek_status(request: Request, nominal: int):
    result = await check_payment_status(PRIVATE_MERCHANT, nominal)
    data = result.get("data")
    if isinstance(data, list) and len(data) > 0:
        request.session["payment_status"] = "paid"
        return {"paid": True}
    return {"paid": False}

@app.get("/success/{book_id}", response_class=HTMLResponse)
async def success(request: Request, book_id: int):
    if request.session.get("payment_status") != "paid":
        return RedirectResponse("/404")
    
    async with httpx.AsyncClient() as client:
        url = f"https://gutendex.com/books/{book_id}/"
        response = await client.get(url)
        if response.status_code == 200:
            books = response.json()
    
            harga = request.session.get("harga")
            tanggal = request.session.get("tanggal")
            pajak = request.session.get("pajak")
            total_bayar = request.session.get("total_bayar")

            connection = get_db_connection()
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO tb_transaksi (id_buku, total, tanggal, status, nama_buku)
                    VALUES (%s, %s, %s, %s, %s)
                """, (book_id, harga, tanggal, "Success", books['title']))

            connection.close()

            try:
                connection = get_db_connection()
                with connection.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO tb_transaksi (id_buku, total, tanggal, status, nama_buku)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (book_id, harga, tanggal, "Success", books['title']))
                    connection.commit()
            except Exception as e:
                print("Gagal insert transaksi:", e)
            finally:
                connection.close()


            request.session.pop("payment_status", None)
            return templates.TemplateResponse("success.html", {
                "request": request,
                "books": books,
                "harga": harga,
                "tanggal": tanggal,
                "pajak": pajak,
                "total_bayar": total_bayar
            })
        request.session.pop("harga", None)
        request.session.pop("tanggal", None)
        request.session.pop("pajak", None)
        request.session.pop("total_bayar", None)


# fake_admin_db = {
#     "admin@gmail.com": {
#         "password": "123",
#         "name": "Admin Perpustakaan"
#     }
# }

# # Login page
# @app.get("/admin/login")
# def admin_login(request: Request):
#     return templates.TemplateResponse("login_admin.html", {"request": request})

# # Login action
# @app.post("/admin/login")
# def login_action(request: Request, email: str = Form(...), password: str = Form(...)):
#     user = fake_admin_db.get(email)
#     if user and user["password"] == password:
#         # request.session["admin_session"] = "valid"
#         return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_302_FOUND)
#     return templates.TemplateResponse("login_admin.html", {"request": request, "message": "Email atau password salah"})

# @app.get("/admin/dashboard", response_class=HTMLResponse)
# async def dashboard(request: Request):
#     async with httpx.AsyncClient() as client:
#         response = await client.get(GUTENDEX_API)
#         if response.status_code == 200:
#             data = response.json()
#             jumlah_buku = data.get("count", 0)
#             connection = get_db_connection()
#             with connection.cursor() as cursor:

#                 cursor.execute("SELECT COUNT(*) as total FROM tb_transaksi")
#                 jumlah_transaksi = cursor.fetchone()["total"]

#                 cursor.execute("SELECT SUM(total) as total FROM tb_transaksi")
#                 total_pendapatan = cursor.fetchone()["total"] or 0

#             connection.close()

#             return templates.TemplateResponse("dashboard_admin.html", {
#                 "request": request,
#                 "jumlah_buku": jumlah_buku,
#                 "jumlah_transaksi": jumlah_transaksi,
#                 "total_pendapatan": format_idr(total_pendapatan),
#                 "admin": "Admin Perpustakaan"
#             })
#         else:
#             return templates.TemplateResponse("login_admin.html", {"request": request, "message": "Email atau password salah"})
        
# @app.get("/admin/laporan")
# def laporan_transaksi(request: Request):
#     connection = get_db_connection()
#     with connection.cursor() as cursor:
#         cursor.execute("SELECT id_buku, total, tanggal, status, nama_buku FROM tb_transaksi")
#         transaksi = cursor.fetchall()
#     connection.close()

#     return templates.TemplateResponse("laporantransaksi.html", {
#         "request": request,
#         "transaksi": transaksi
#     })
