# Use a lightweight Python base
FROM python:3.12-slim

# Install system packages including ffmpeg and libopus
RUN apt update && apt install -y ffmpeg libopus0 && apt clean

# Set working directory
WORKDIR /app

# Copy all files into the container
COPY . .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot
CMD ["python", "bot.py"]
