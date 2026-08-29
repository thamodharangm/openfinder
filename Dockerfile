# ============================================================================
# OpenFinder Production Dockerfile
# Optimized for Render, Railway, Fly.io, AWS ECS, GCP Cloud Run, and Docker Compose
# ============================================================================

FROM python:3.11-slim AS runner

# Set production environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PORT=8000 \
    OPENFINDER_ENV=production \
    OPENFINDER_DATA_DIR=/app/data

WORKDIR /app

# Install minimal OS dependencies & curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create application data directory and non-root user
RUN useradd -m -u 10001 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

# Copy application source code
COPY --chown=appuser:appuser . .

# Switch to non-root user for enterprise security
USER appuser

# Expose default HTTP port
EXPOSE 8000

# Container Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Default command launches FastAPI Universal Dual Protocol API Server
CMD ["sh", "-c", "python -m uvicorn api_server:app --host 0.0.0.0 --port ${PORT}"]
