# database.py
import os
import urllib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DB_USER = os.getenv("DB_USER", "sa")
DB_PASS = os.getenv("DB_PASS", "YourStrong!Passw0rd")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "1433")
DB_NAME = os.getenv("DB_NAME", "CafeSyncDB")

params = urllib.parse.quote_plus(
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={DB_HOST},{DB_PORT};"
    f"DATABASE={DB_NAME};"
    f"UID={DB_USER};"
    f"PWD={DB_PASS};"
    f"TrustServerCertificate=yes;"
)

SQLALCHEMY_DATABASE_URL = f"mssql+pyodbc:///?odbc_connect={params}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_size=10,           # Maximum number of permanent connections to keep alive
    max_overflow=20,        # Maximum number of temporary connections allowed during spikes
    pool_timeout=30,        # Maximum time (seconds) to wait for a connection before failing
    pool_pre_ping=True,     # Pessimistic disconnect handling (Liveness check)
    fast_executemany=True   # ODBC Driver optimization for bulk operations
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()