# Use a lightweight Python 3.11 base image
FROM python:3.11-slim

# Set environment variables for Python and Gunicorn
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000

# Set working directory
WORKDIR /app

# Install system dependencies for PyMuPDF, pdf2image, pytesseract, pyttsx3, build tools, swig, and Redis
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
RUN pip install --no-cache-dir -r requirements.txt --use-pep517 || { echo "Failed to install dependencies"; exit 1; }

# Debug step: Verify PyMuPDF is installed
RUN python -c "import PyMuPDF; print('PyMuPDF installed successfully:', PyMuPDF.__version__)" || { echo "PyMuPDF installation failed"; exit 1; }

# Copy the rest of the application
COPY . .

# Expose the port
EXPOSE 10000

# Command to start Redis and run the app with optimized Gunicorn settings
CMD ["sh", "-c", "redis-server --daemonize yes && gunicorn --bind 0.0.0.0:$PORT --workers 4 --threads 8 --timeout 120 --log-level info app:app"]
