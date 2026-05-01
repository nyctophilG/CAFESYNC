# CAFESYNC
FastAPI backend for CafeSync. Features robust technical monitoring, connection pooling, and containerized SQL Server integration for high-availability performance tracking.

# CafeSync Technical Monitoring API

Backend service for the CafeSync application, engineered with a focus on system stability, latency tracking, and technical risk mitigation.

## Architecture

*   **Framework:** Python 3.10+ & FastAPI
*   **Database:** Microsoft SQL Server (Containerized via Docker)
*   **ORM:** SQLAlchemy with `pyodbc`
*   **Monitoring:** Custom middleware for API latency and database transaction logging

## Pod 2 Responsibilities (Technical Monitoring)

This repository fulfills the Technical Monitoring requirements of the project:
1.  **Lead Development:** Maintainable MVC architecture and strict typing.
2.  **Operations tracking:** Monitoring system uptime, 500 error rates, and API response times.
3.  **QA/Testing:** Mitigating technical debt and ensuring reliable database pooling under load.

## Environment Setup (Ubuntu / Linux)

### 1. System Dependencies
You must install the Microsoft ODBC Driver 18 to interface with SQL Server.
```bash
curl [https://packages.microsoft.com/keys/microsoft.asc](https://packages.microsoft.com/keys/microsoft.asc) | sudo tee /etc/apt/trusted.gpg.d/microsoft.asc
curl [https://packages.microsoft.com/config/ubuntu/$(lsb_release](https://packages.microsoft.com/config/ubuntu/$(lsb_release) -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc-dev
