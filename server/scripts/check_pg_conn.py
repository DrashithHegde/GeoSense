import psycopg2
import sys

HOST = '127.0.0.1'
PORT = 5432
DB = 'geosense'
USER = 'postgres'
PASSWORD = 'postgres'

try:
    conn = psycopg2.connect(host=HOST, port=PORT, dbname=DB, user=USER, password=PASSWORD, connect_timeout=5)
    cur = conn.cursor()
    cur.execute('SELECT current_database(), current_user')
    print('OK', cur.fetchone())
    cur.close()
    conn.close()
    sys.exit(0)
except Exception as e:
    print('ERR', type(e).__name__, e)
    sys.exit(2)
