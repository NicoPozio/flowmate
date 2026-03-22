FROM python:3.12-slim

WORKDIR /backend

COPY requirements.txt . 

RUN apt-get update && apt-get install -y \
    gcc \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY src/backend/ .

EXPOSE 8003

# CMD ["uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8003"]
