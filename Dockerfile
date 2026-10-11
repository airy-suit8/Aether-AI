FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libsqlite3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ /app/backend/

# Copy built frontend (assuming we build it on the host first, or use a multi-stage build later)
# COPY frontend/dist/ /app/backend/static/

# Set environment variables
ENV PYTHONPATH=/app
ENV AETHER_DB_PATH=/app/data/aether.db

# Create directories for persistence
RUN mkdir -p /app/data /app/backend/logs /app/backend/vector_store

# Expose port
EXPOSE 8000

# Run the application
WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
