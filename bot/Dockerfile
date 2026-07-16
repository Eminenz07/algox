FROM python:3.12-slim

# Force stdout/stderr to be unbuffered (immediate logging flush)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Hugging Face Spaces require the app to bind to port 7860
EXPOSE 7860

# Run the bot orchestrator
CMD ["python", "main.py"]
