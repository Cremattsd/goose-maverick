# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
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

# Copy Tailwind config and create input.css
COPY tailwind.config.js .
RUN mkdir -p static/css && echo "@tailwind base;\n@tailwind components;\n@tailwind utilities;" > static/css/input.css

# Build Tailwind CSS
RUN npm run build

# Copy the rest of the app
COPY . .

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port
EXPOSE 5000

# Command to run the app
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
