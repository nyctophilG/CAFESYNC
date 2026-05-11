# Multi-stage isn't needed for our app — single stage keeps things simple.
# Python 3.11-slim is small (~150MB) and has good compatibility with our deps.
FROM python:3.11-slim

# Don't write .pyc files, don't buffer output (so logs show up immediately
# in Render's log viewer).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System packages needed at build/runtime:
#  - build-essential & libffi-dev: for compiling bcrypt and cryptography
#    (webauthn pulls cryptography as a transitive dep)
#  - libjpeg & zlib: for Pillow (used by qrcode[pil])
# These add ~80MB to the image but make `pip install` reliable.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in their own layer so re-building the image after
# code-only changes doesn't reinstall everything.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app. .dockerignore filters out tests, .git, etc.
COPY . .

# Render injects the PORT env var (typically 10000). Default to 8000 locally.
ENV PORT=8000
EXPOSE 8000

# Run uvicorn directly. --proxy-headers tells starlette to trust the
# X-Forwarded-* headers Render's load balancer sets (so request.url is
# https not http, and request.client.host is the real client IP, not
# Render's internal proxy).
#
# We use sh -c so PORT is expanded at runtime, not at image-build time.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
