FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py config.py deals_api.py posted_store.py ./

ENV PYTHONUNBUFFERED=1

CMD ["python", "bot.py"]
