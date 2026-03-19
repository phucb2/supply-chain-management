FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY libs/ /libs/
COPY services/stream_processor/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/stream_processor/ .

CMD ["faust", "-A", "app.main", "worker", "-l", "info"]
