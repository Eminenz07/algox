FROM python:3.12-slim

# Force stdout/stderr to be unbuffered (immediate logging flush)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements from bot folder and install
COPY bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all bot source code into container
COPY bot/ .

# Hugging Face / Render require the app to bind to port 7860 (Hugging Face default) or Render's PORT env var
EXPOSE 7860

# Run the bot orchestrator
CMD ["python", "main.py"]
