# Use an official Python runtime as the base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (for Tesseract, build tools, and frontend)
RUN apt-get update && apt-get install -y \
    build-essential \
    tesseract-ocr \
    libtesseract-dev \
    libpoppler-cpp-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js and npm for frontend build (using Node 20)
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY requirements.txt .
COPY package.json .

# Upgrade pip and install Python dependencies
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Install npm dependencies and clear cache to avoid EINTEGRITY errors
RUN npm cache clean --force && npm install

# Copy the rest of the application
COPY . .

# Build frontend (if using TailwindCSS/Webpack)
RUN npm run build

# Expose port for Render
EXPOSE 8000

# Run the Flask app with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "app:app"]
