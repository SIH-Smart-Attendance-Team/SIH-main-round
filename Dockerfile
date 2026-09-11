# Dockerfile for WeatherGPT Backend
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create media directory
RUN mkdir -p /tmp/weathergpt_media

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "backend_app_factory:app", "--host", "0.0.0.0", "--port", "8000"]