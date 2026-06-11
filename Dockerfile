FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY public ./public

RUN mkdir -p downloads source jobs

EXPOSE 8787

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8787} --timeout 900 --workers 1 app:app"]
