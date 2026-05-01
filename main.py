import os
import urllib
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Environment variable extraction
DB_USER = os.getenv("DB_USER", "sa")
DB_PASS = os.getenv("DB_PASS", "YourStrong!Passw0rd")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "1433")
DB_NAME = os.getenv("DB_NAME", "CafeSyncDB")

# Architecting the connection string for the ODBC Driver 18
params = urllib.parse.quote_plus(
    f"DRIVER={{ODBC Driver 18 for SQL Server}};"
    f"SERVER={DB_HOST},{DB_PORT};"
    f"DATABASE={DB_NAME};"
    f"UID={DB_USER};"
    f"PWD={DB_PASS};"
    f"TrustServerCertificate=yes;"
)

# Engine configuration with connection pooling for high-availability
engine = create_engine(
    f"mssql+pyodbc:///?odbc_connect={params}",
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    echo=False # Set to True locally if you need to monitor raw SQL query compilation
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Initialize API
app = FastAPI(title="CafeSync Technical Monitoring API")

# Dependency injection for route handlers
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health")
def health_check():
    """Basic endpoint to verify API routing and uptime."""
    return {"status": "healthy", "service": "CafeSync Core"}