FROM python:3.9-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    imagemagick \
    && rm -rf /var/lib/apt/lists/*

# Python setup
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node.js for Tailwind build
RUN apt-get update && apt-get install -y curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

# Node dependencies
COPY package.json .
RUN npm cache clean --force && npm install

# ✅ Now copy everything (including static/css/input.css)
COPY . .

# ✅ Build AFTER all files are available
RUN npm run build

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
