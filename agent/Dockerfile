FROM python:3.11-slim

# Install Node.js (LTS) for the @openai/codex CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @openai/codex \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml requirements.txt* ./
RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN pip install --no-cache-dir -e . --no-deps

EXPOSE 8101

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8101/api/health')"

CMD ["/app/entrypoint.sh"]
