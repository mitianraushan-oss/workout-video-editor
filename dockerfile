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

# Command to run the app.
# --workers 1  : keep a single worker so the in-memory processing_status dict is
#                consistent (multiple workers => status polls could hit a worker
#                that never saw the task => stuck at 0% / "task not found").
# --threads 8  : gthread worker so long background jobs (OpenCV analysis / ffmpeg)
#                don't starve the arbiter heartbeat and get the worker killed.
# --timeout 600: don't kill a worker mid-job (default is 30s, which aborts real
#                video processing and leaves the UI stuck at 0%).
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--workers", "1", "--threads", "8", "--timeout", "600", "app:app"]
