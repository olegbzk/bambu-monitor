FROM python:3.11-alpine

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache \
    curl \
    shadow 

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY bambu-monitor.py .
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

RUN groupadd -r -g 10101 appuser && useradd -r -u 10101 -g appuser appuser
RUN chown -R appuser:appuser /app
USER 10101

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

ENTRYPOINT [ "/bin/sh", "/app/docker-entrypoint.sh" ]

