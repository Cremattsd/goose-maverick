# Use the official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system and Node dependencies
RUN apt-get update -y && \
    apt-get install -y curl gnupg build-essential tesseract-ocr libtesseract-dev poppler-utils && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean

# Copy Python dependency files
COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy Node dependency files
COPY package.json ./

# Optional: only copy package-lock.json if it exists
COPY package-lock.json ./ 

# Install Node dependencies
RUN npm install

# Copy rest of app
COPY . .

# Build Tailwind CSS
RUN npm run build:css

# Expose the port Render will use
EXPOSE 10000

# Start the app with Gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:10000", "app:app"]