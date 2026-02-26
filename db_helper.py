import libsql_experimental as libsql
import os

TURSO_URL = os.getenv("libsql://daissy-tsb-chashvith.aws-ap-south-1.turso.io")
TURSO_TOKEN = os.getenv("eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3NzIwODc3NDEsImlkIjoiMDE5Yzk4YTctN2YwMS03MzNlLTkxY2UtMmU1ZTNhNmFmM2Y5IiwicmlkIjoiZDI0ZDc2MGEtODQ2Yy00ZGE5LWI3ZDktZTY0MWZlM2M2OGJiIn0.QEHOEUwPOpmABXveYgosPhup1IKuw4GgcS8eLxr_PP0ZlOxjej-V6QLgg_lspGsawjz-97gaJKaPhPiEdEH1Ag")

def get_connection():
    """Returns a Turso (cloud SQLite) connection. Syncs remote state first."""
    conn = libsql.connect("local_cache.db", sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
    conn.sync()
    return conn