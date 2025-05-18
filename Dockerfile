FROM python:3.9-slim

WORKDIR /app

# Install system dependencies and Node.js
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    imagemagick \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy node modules and create input.css before npm install
COPY package.json .
COPY tailwind.config.js .

# ⬇️ Create the missing input.css BEFORE build
RUN mkdir -p static/css && echo -e "@tailwind base;\n@tailwind components;\n@tailwind utilities;" > static/css/input.css

# Install and build
RUN npm install && npm run build

# Copy the rest of the app
COPY . .

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
