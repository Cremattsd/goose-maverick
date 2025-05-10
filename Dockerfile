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
       && apt-get clean

   # Install Node.js and npm for Tailwind CSS
   RUN apt-get install -y curl && \
       curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
       apt-get install -y nodejs

   # Copy dependency files
   COPY package.json requirements.txt ./

   # Install Node.js dependencies and build Tailwind CSS
   RUN npm install && npm run build:css

   # Install Python dependencies
   RUN pip install --no-cache-dir -r requirements.txt

   # Copy the rest of the application
   COPY . .

   # Expose the port Render will use
   EXPOSE 10000

   # Command to run the app
   CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:10000", "app:app"]
