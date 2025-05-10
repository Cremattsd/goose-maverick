# Use the official Python 3.11 image as the base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update -y && \
    apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    curl && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean

# Copy dependency files
COPY requirements.txt package.json ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN npm install

# 🐛 Debug file structure and contents before Tailwind build
RUN echo "📂 rc/ directory:" && ls -la rc && \
    echo "📂 static/ directory:" && ls -la static && \
    echo "📄 rc/input.css contents:" && cat rc/input.css || true

# Now try to build Tailwind CSS
RUN npm run build:css

# Copy the rest of the app
COPY . .

# Expose the port Render will use
EXPOSE 10000

# Command to run the app
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:10000", "app:app"]
