FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt tzdata
COPY bot.py .
# topics.db is opened relative to the working directory, so run from the volume.
WORKDIR /data
CMD ["python", "-u", "/app/bot.py"]
