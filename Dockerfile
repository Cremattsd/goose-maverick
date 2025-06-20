# ---------- Stage 1: Build Frontend ----------
FROM node:20 AS frontend-builder

WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

# ---------- Stage 2: Backend Setup ----------
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    tesseract-ocr \
    libtesseract-dev \
    libpoppler-cpp-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy application and built frontend
COPY --from=frontend-builder /app /app

# Set environment variables
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

EXPOSE $PORT

# Run the Flask app with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "--workers", "3", "app:app"]
