# Use official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements headers
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn

# Copy application code
COPY . .

# Expose port (Cloud Run expects 8080)
EXPOSE 8080

# Migration check on startup?
# Ideally migration is manual or an INIT container.
# For simplicity, we can run it before starting access, but careful with duplicates
# The script checks if users exist so it's idempotent.
CMD python migrate_users.py && gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app.web.server:app
