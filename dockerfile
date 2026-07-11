# Use a stable, supported Python version
FROM python:3.11-slim

# FFmpeg for processing; Noto fonts so burned-in captions render in
# non-Latin scripts (Hindi, CJK, Arabic) instead of empty boxes
RUN apt-get update && \
    apt-get install -y ffmpeg fonts-noto-core fonts-noto-cjk && \
    apt-get clean

# Set the working directory inside the container
WORKDIR /app

# Copy requirements first (to cache them)
COPY requirements.txt .

# Upgrade pip and install Python packages
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port Render expects
EXPOSE 10000

# Command to run the app
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "app:app"]
