# Torch.AI — Full-Stack Engineer Exercise
# Base: RHEL UBI 9.5 (also satisfies DevOps Engineer exercise requirement)
FROM registry.access.redhat.com/ubi9/python-311:latest

LABEL maintainer="Ben Brown <ben@oakenai.com>"
LABEL description="Naval SITREP Event Parser — Torch.AI Full-Stack Exercise"
LABEL version="1.0.0"

# Switch to root for package installation
USER root

# Install curl for healthcheck
RUN dnf install -y curl && dnf clean all

# Create app directory
WORKDIR /app

# Copy requirements first (layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user for runtime
RUN useradd -r -u 1001 -g root appuser && \
    chown -R appuser:root /app
USER appuser

# Expose port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
