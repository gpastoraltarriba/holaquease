# test_connection.py
import psycopg2
from urllib.parse import urlparse


def test_connection():
    print("🔍 Probando conexión con psycopg2...")

    try:
        # Tu connection string
        db_url = "postgresql://postgres.whkclbhcvpxfbaznkcvm:TuNuevaContraseñaSimple@aws-0-eu-west-3.pooler.supabase.com:6543/postgres"

        conn = psycopg2.connect(
            host='aws-0-eu-west-3.pooler.supabase.com',
            port=6543,
            user='postgres.whkclbhcvpxfbaznkcvm',
            password='TuNuevaContraseñaSimple',
            database='postgres',
            sslmode='require'
        )

        print("✅ ✅ ✅ CONEXIÓN EXITOSA con psycopg2!")

        # Probar consulta
        cursor = conn.cursor()
        cursor.execute('SELECT version()')
        version = cursor.fetchone()
        print(f"✅ PostgreSQL: {version[0]}")

        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    success = test_connection()
    if success:
        print("\n🎯 ¡psycopg2 funciona! Actualiza tu aplicación.")
    else:
        print("\n💡 Verifica tu contraseña en Supabase Dashboard")