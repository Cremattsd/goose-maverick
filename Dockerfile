# Use a lightweight Python 3.11 base image
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/usr/local/lib/python3.11/site-packages

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    make \
    gcc \
    g++ \
    swig \
    libmupdf-dev \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    libopenjp2-7-dev \
    liblcms2-dev \
    libtiff-dev \
    libpng-dev \
    libtesseract-dev \
    libleptonica-dev \
    tesseract-ocr \
    poppler-utils \
    curl \
    libespeak1 \
    libespeak-dev \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x and npm
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest

# Copy Node.js stuff first to leverage caching
COPY package.json tailwind.config.js ./
COPY static/ static/
RUN npm install
RUN npx update-browserslist-db@latest
RUN mkdir -p static/js && \
    cp node_modules/chart.js/dist/chart.umd.js static/js/chart.js && \
    cp node_modules/socket.io-client/dist/socket.io.min.js static/js/socket.io.min.js
RUN npm run build

# Update pip and install Python dependencies
RUN pip install --upgrade pip
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt --use-pep517
RUN python -c "import dotenv; print('python-dotenv is installed!')"

# Copy the rest of the app
COPY . .

# Expose the app port for Docker (Render sets $PORT)
EXPOSE 10000

# Run Gunicorn with dynamic port from Render
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 4 --threads 8 --timeout 120 --log-level info app:app"]
