# Use a lightweight Python 3.11 base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for PyMuPDF (MuPDF, Leptonica, Tesseract), pdf2image (poppler-utils), build tools, and swig
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
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x and npm (use the latest npm version to avoid potential version issues)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest

# Copy Node.js dependency files and static assets first to leverage caching
COPY package.json tailwind.config.js ./
COPY static/ static/
RUN npm install

# Update Browserslist database to fix caniuse-lite warning
RUN npx update-browserslist-db@latest

# Copy Chart.js and Socket.io to static/js for local use
RUN mkdir -p static/js && \
    cp node_modules/chart.js/dist/chart.umd.js static/js/chart.js && \
    cp node_modules/socket.io-client/dist/socket.io.min.js static/js/socket.io.min.js

# Build Tailwind CSS
RUN npm run build

# Update pip to the latest version
RUN pip install --upgrade pip

# Copy Python requirements and install dependencies to leverage caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --use-pep517

# Copy the rest of the application
COPY . .

# Expose the port (Render will override this with the PORT env variable)
EXPOSE 5000

# Command to run the app, using the PORT environment variable with optimized gunicorn settings
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 app:app"]
