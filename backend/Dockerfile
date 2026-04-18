FROM python:3.11-slim AS base

WORKDIR /app

# System deps: libmagic (upload mime sniff), build tools for asyncpg/pillow,
# fonts for reportlab + pdfplumber rendering.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libmagic1 \
        libjpeg62-turbo \
        zlib1g \
        fonts-dejavu-core \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . python-magic

COPY . .

RUN useradd --create-home --uid 10001 elfie \
    && mkdir -p /app/artifacts /app/.devlogs \
    && chown -R elfie:elfie /app
USER elfie

EXPOSE 8000

# Production entrypoint runs migrations then uvicorn (multi-worker, no --reload).
CMD ["sh", "/app/scripts/docker_start.sh"]
