FROM python:3.11-slim

WORKDIR /app

# System deps: libmagic for python-magic (upload validation)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir . python-magic

EXPOSE 8000

CMD ["sh", "/app/scripts/docker_start.sh"]
