# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
  tesseract-ocr libtesseract-dev poppler-utils curl \
  && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
  && apt-get install -y nodejs \
  && apt-get clean

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && pip install --no-cache-dir -r requirements.txt

# Copy Node files and install Tailwind
COPY package.json package-lock.json ./
RUN npm install

# Copy the rest of the app
COPY . .

# Build Tailwind CSS
RUN npm run build:css

# Expose port
EXPOSE 10000

# Start app
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:10000", "app:app"]