# Use the official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update -y && \
    apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    curl \
    build-essential \
    nodejs \
    npm \
    git && \
    apt-get clean

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Setup Node.js environment and install TailwindCSS
COPY package.json ./
RUN npm install

# Copy application files
COPY . .

# Build Tailwind CSS
RUN npm run build:css || echo "⚠️ Tailwind build failed, continuing..."

# Expose app port
EXPOSE 10000

# Run the app with Gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:10000", "app:app"]