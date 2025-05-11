# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system packages
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Install Node (Tailwind/Webpack) dependencies
COPY package.json package-lock.json ./
RUN npm install

# Copy all project files
COPY . .

# Build Tailwind and JS (if needed)
RUN npm run build:css || echo "Tailwind build failed"
RUN npm run build:js || echo "JS build failed"

# Expose Flask port
EXPOSE 10000

# Start Flask app via gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:10000", "app:app"]