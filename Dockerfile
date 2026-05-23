FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps required by WeasyPrint (Pango/Cairo) and Pillow.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-dejavu \
        fonts-noto \
        fonts-noto-color-emoji \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better build cache.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Then copy the source.
COPY app ./app
COPY bot.py ./

ENV DATA_DIR=/tmp/bot_data
RUN mkdir -p /tmp/bot_data && chown -R nobody:nogroup /tmp/bot_data
USER nobody

# Render injects $PORT at runtime. The bot binds to it when WEBHOOK_BASE_URL is set.
EXPOSE 8080

CMD ["python", "bot.py"]
