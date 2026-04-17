# Streaming Benchmark Runbook

Use this guide when you need to run or compare end-to-end benchmark results for Kafka, RabbitMQ, and MQTT in Grafana.

## Install Benchmark Dependencies

```bash
pip install -r scripts/requirements-benchmark.txt
```

## Configure Targets

Set benchmark variables in `.env` (see `.env.example`):
- `KAFKA_BOOTSTRAP_SERVERS` for in-repo Kafka.
- `RABBITMQ_URL`, `RABBITMQ_QUEUE` for external RabbitMQ.
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC` for external MQTT.
- `OTEL_EXPORTER_OTLP_ENDPOINT` for metric export (`http://localhost:4317` when running with local compose).

Common workload controls:
- `BENCHMARK_TARGET_MESSAGES`
- `BENCHMARK_MESSAGE_SIZE`
- `BENCHMARK_TIMEOUT_SECONDS`
- `BENCHMARK_SCENARIO`
- `BENCHMARK_RUN_ID` (optional; auto-generated if empty)

## Run Benchmarks

Run each broker independently with the same workload profile:

```bash
python scripts/benchmark_streaming.py --broker kafka --scenario baseline
python scripts/benchmark_streaming.py --broker rabbitmq --scenario baseline
python scripts/benchmark_streaming.py --broker mqtt --scenario baseline
```

Each run prints a JSON summary with:
- sent/received messages
- delivery ratio
- throughput (messages/second)
- p50/p95/p99/max latency in milliseconds

## Grafana Dashboard

Open Grafana and use dashboard **Streaming Broker Benchmark**.

Expected key panels:
- send and receive throughput by broker
- e2e latency p50/p95/p99 by broker
- delivery success ratio by broker
- latest run duration by broker

Use template filters:
- `scenario` to compare profiles (baseline, stress, etc.)
- `run_id` to inspect specific benchmark runs

## Suggested Profiles

- Baseline: lower concurrency, fixed message size (stable comparison).
- Stress: higher message volume or larger payload (saturation behavior).

Keep profiles identical across Kafka, RabbitMQ, and MQTT to make the dashboard comparison meaningful.
