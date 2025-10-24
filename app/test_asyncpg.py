# test_asyncpg.py
import os, asyncio, asyncpg

HOST = "127.0.0.1"
PORT = 5432
DB   = os.getenv("DB_NAME", "fitness_ai")
USER = os.getenv("DB_USER", "usuario")
PASS = os.getenv("DB_PASSWORD", "tu_contraseña")  # pon tu pass aquí si no usas variables por piezas

async def go():
    try:
        conn = await asyncpg.connect(
            host=HOST, port=PORT, user=USER, password=PASS, database=DB,
            ssl=None  # equivale a ?ssl=disable en tu URL
        )
        v = await conn.fetchval("SELECT 1")
        print("SELECT 1 =", v)
        await conn.close()
        print("OK asyncpg")
    except Exception as e:
        print("ERROR asyncpg:", repr(e))

asyncio.run(go())
