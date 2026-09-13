# Use the official Python 3.11 slim image
FROM python:3.11-slim

# Hugging Face Spaces specific environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/user/app \
    HOME=/home/user

# Create user with UID 1000 to comply with HF Spaces constraints
RUN useradd -m -u 1000 user

# Set the working directory to the user's home app directory
WORKDIR $HOME/app

# Install system dependencies (required for pg_config and some native packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Switch to the non-root user
USER user

# Copy the requirements file and install dependencies in user context
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Add the user's local bin to PATH
ENV PATH="$HOME/.local/bin:$PATH"

# Copy the rest of the application files
COPY --chown=user:user . .

# Expose port 7860 as mandated by Hugging Face Spaces
EXPOSE 7860

# Start Uvicorn bound to 0.0.0.0 and port 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
