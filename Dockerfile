FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium

COPY server.py .

ENV PORT=8090
ENV HEADLESS=true
ENV BROWSER_TIMEOUT=60000
ENV SESSION_FILE=/data/session.json

VOLUME ["/data"]
EXPOSE 8090

CMD ["python", "server.py"]
