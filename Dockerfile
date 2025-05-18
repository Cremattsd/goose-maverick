# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for PyMuPDF (MuPDF, Leptonica, Tesseract), pdf2image (poppler-utils), build tools, and swig
RUN apt-get update && apt-get install -y \
    curl \
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
    && rm -rf /var/lib/apt/lists/*

# Install Node.js and npm
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@11.4.0

# Copy package.json and install Node.js dependencies
COPY package.json .
RUN npm install

# Update Browserslist database to fix caniuse-lite warning
RUN npx update-browserslist-db@latest

# Copy Chart.js and Socket.io to static/js for local use
RUN mkdir -p static/js && \
    cp node_modules/chart.js/dist/chart.umd.js static/js/chart.js && \
    cp node_modules/socket.io-client/dist/socket.io.min.js static/js/socket.io.min.js

# Copy Tailwind config and static files (including input.css)
COPY tailwind.config.js .
COPY static/ static/

# Build Tailwind CSS
RUN npm run build

# Copy the rest of the app
COPY . .

# Update pip to the latest version
RUN pip install --upgrade pip

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port (Render will override this with the PORT env variable)
EXPOSE 5000

# Command to run the app, using the PORT environment variable
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT app:app"]