# === Base Python image for Flask backend ===
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# === System dependencies ===
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    curl \
    gnupg \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# === Install Node.js 18 for Tailwind ===
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g npm

# === Copy and install Python requirements ===
COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# === Copy and install Node (Tailwind) deps ===
COPY package.json package-lock.json ./
RUN npm install

# === Copy the rest of the app (backend + frontend) ===
COPY . .

# === Tailwind Build ===
RUN npm run build:css || echo '⚠️ Tailwind build failed, continuing...'

# Ensure static folder exists
RUN mkdir -p static

# === Expose port ===
EXPOSE 10000

# === Run it ===
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:10000", "app:app"]