FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8765 \
    DATABASE_PATH=/app/data/database/epic.db \
    SESSIONS_PATH=/app/data/sessions \
    STATE_PATH=/app/data/state

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium --with-deps \
    && apt-get update && apt-get install -y --no-install-recommends \
        net-tools procps xvfb x11vnc websockify novnc \
    && rm -rf /var/lib/apt/lists/*

RUN websockify --help | head -n 5

COPY app ./app

RUN mkdir -p /app/data/database /app/data/sessions /app/data/state

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
