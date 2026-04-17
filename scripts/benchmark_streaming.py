"""
Streaming broker benchmark for Kafka, RabbitMQ, and MQTT.

Usage example:
  python scripts/benchmark_streaming.py --broker kafka --scenario baseline
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource


def _now_ns() -> int:
    return time.time_ns()


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass
class BenchmarkConfig:
    broker: str
    scenario: str
    run_id: str
    topic: str
    message_size: int
    concurrency: int
    target_messages: int
    timeout_seconds: int
    kafka_bootstrap_servers: str
    rabbitmq_url: str
    rabbitmq_queue: str
    mqtt_host: str
    mqtt_port: int
    mqtt_topic: str
    otlp_endpoint: str

    @classmethod
    def from_env(cls, broker: str, scenario: str) -> "BenchmarkConfig":
        return cls(
            broker=broker,
            scenario=scenario,
            run_id=os.getenv("BENCHMARK_RUN_ID", str(uuid.uuid4())),
            topic=os.getenv("BENCHMARK_TOPIC", "benchmark.e2e"),
            message_size=_read_int("BENCHMARK_MESSAGE_SIZE", 256),
            concurrency=_read_int("BENCHMARK_CONCURRENCY", 1),
            target_messages=_read_int("BENCHMARK_TARGET_MESSAGES", 1000),
            timeout_seconds=_read_int("BENCHMARK_TIMEOUT_SECONDS", 120),
            kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            rabbitmq_url=os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
            rabbitmq_queue=os.getenv("RABBITMQ_QUEUE", "benchmark.e2e"),
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=_read_int("MQTT_PORT", 1883),
            mqtt_topic=os.getenv("MQTT_TOPIC", "benchmark/e2e"),
            otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
        )


class BrokerAdapter:
    def connect(self) -> None:
        raise NotImplementedError

    def prepare(self) -> None:
        raise NotImplementedError

    def start_consumer(self, on_message: Any) -> None:
        raise NotImplementedError

    def publish(self, payload: bytes) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def wait_until_ready(self, timeout_seconds: float = 10.0) -> bool:
        return True

    def after_publish(self) -> None:
        return None


class KafkaAdapter(BrokerAdapter):
    def __init__(self, config: BenchmarkConfig):
        from confluent_kafka import Consumer, Producer

        self._topic = config.topic
        self._producer = Producer({"bootstrap.servers": config.kafka_bootstrap_servers, "acks": "all"})
        self._consumer = Consumer(
            {
                "bootstrap.servers": config.kafka_bootstrap_servers,
                "group.id": f"benchmark-{config.run_id}",
                "auto.offset.reset": "earliest",
            }
        )
        self._running = False
        self._thread: threading.Thread | None = None
        self._assigned = threading.Event()

    def connect(self) -> None:
        def _on_assign(_consumer: Any, _partitions: Any) -> None:
            self._assigned.set()

        self._consumer.subscribe([self._topic], on_assign=_on_assign)

    def prepare(self) -> None:
        # Topic is expected to exist in this project stack (created by init script).
        return None

    def start_consumer(self, on_message: Any) -> None:
        self._running = True
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not self._assigned.is_set():
            self._consumer.poll(0.1)
        if not self._assigned.is_set():
            raise RuntimeError("kafka consumer was not assigned partitions in time")

        def _poll_loop() -> None:
            while self._running:
                msg = self._consumer.poll(0.2)
                if msg is None:
                    continue
                if msg.error():
                    continue
                try:
                    on_message(msg.value())
                except Exception:
                    # Keep consumer loop alive even if a malformed message is encountered.
                    continue

        self._thread = threading.Thread(target=_poll_loop, daemon=True)
        self._thread.start()

    def wait_until_ready(self, timeout_seconds: float = 10.0) -> bool:
        _ = timeout_seconds
        return self._assigned.is_set()

    def publish(self, payload: bytes) -> None:
        self._producer.produce(self._topic, payload)
        self._producer.poll(0)

    def after_publish(self) -> None:
        self._producer.flush(5)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._consumer.close()
        self._producer.flush(5)


class RabbitMQAdapter(BrokerAdapter):
    def __init__(self, config: BenchmarkConfig):
        import pika

        self._rabbitmq_url = config.rabbitmq_url
        self._queue_name = config.rabbitmq_queue
        self._connection = pika.BlockingConnection(pika.URLParameters(config.rabbitmq_url))
        self._channel = self._connection.channel()
        self._running = False
        self._thread: threading.Thread | None = None
        self._consumer_connection = None
        self._consumer_channel = None

    def connect(self) -> None:
        return None

    def prepare(self) -> None:
        self._channel.queue_declare(queue=self._queue_name, durable=False)

    def start_consumer(self, on_message: Any) -> None:
        self._running = True

        def _consume_loop() -> None:
            import pika

            self._consumer_connection = pika.BlockingConnection(
                pika.URLParameters(self._rabbitmq_url)
            )
            self._consumer_channel = self._consumer_connection.channel()
            self._consumer_channel.queue_declare(queue=self._queue_name, durable=False)
            while self._running:
                method_frame, _, body = self._consumer_channel.basic_get(
                    queue=self._queue_name, auto_ack=True
                )
                if method_frame:
                    on_message(body)
                else:
                    time.sleep(0.02)
            self._consumer_connection.close()

        self._thread = threading.Thread(target=_consume_loop, daemon=True)
        self._thread.start()

    def publish(self, payload: bytes) -> None:
        self._channel.basic_publish(exchange="", routing_key=self._queue_name, body=payload)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._connection.close()


class MqttAdapter(BrokerAdapter):
    def __init__(self, config: BenchmarkConfig):
        import paho.mqtt.client as mqtt

        self._mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._host = config.mqtt_host
        self._port = config.mqtt_port
        self._topic = config.mqtt_topic
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None

        def _on_message(_client: Any, _userdata: Any, msg: Any) -> None:
            self._queue.put(bytes(msg.payload))

        self._mqtt.on_message = _on_message

    def connect(self) -> None:
        self._mqtt.connect(self._host, self._port, 60)
        self._mqtt.loop_start()

    def prepare(self) -> None:
        self._mqtt.subscribe(self._topic)

    def start_consumer(self, on_message: Any) -> None:
        self._running = True

        def _consume_loop() -> None:
            while self._running:
                try:
                    payload = self._queue.get(timeout=0.2)
                    on_message(payload)
                except queue.Empty:
                    continue

        self._thread = threading.Thread(target=_consume_loop, daemon=True)
        self._thread.start()

    def publish(self, payload: bytes) -> None:
        self._mqtt.publish(self._topic, payload, qos=0)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._mqtt.loop_stop()
        self._mqtt.disconnect()


def make_adapter(config: BenchmarkConfig) -> BrokerAdapter:
    if config.broker == "kafka":
        return KafkaAdapter(config)
    if config.broker == "rabbitmq":
        return RabbitMQAdapter(config)
    if config.broker == "mqtt":
        return MqttAdapter(config)
    raise ValueError(f"Unsupported broker: {config.broker}")


def setup_meter_provider(service_name: str, otlp_endpoint: str) -> MeterProvider:
    resource = Resource.create({"service.name": service_name})
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=otlp_endpoint), export_interval_millis=5_000
    )
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)
    return provider


def run_benchmark(config: BenchmarkConfig) -> dict[str, Any]:
    meter = metrics.get_meter("stream-benchmark")

    sent_counter = meter.create_counter(
        "benchmark_messages_sent", description="Messages sent by benchmark runner"
    )
    received_counter = meter.create_counter(
        "benchmark_messages_received", description="Messages received by benchmark runner"
    )
    latency_hist = meter.create_histogram(
        "benchmark_e2e_latency", unit="ms", description="End-to-end latency from publish to receive"
    )
    run_duration_hist = meter.create_histogram(
        "benchmark_run_duration_seconds", unit="s", description="Benchmark run duration seconds"
    )

    labels = {
        "broker": config.broker,
        "scenario": config.scenario,
        "message_size": str(config.message_size),
        "concurrency": str(config.concurrency),
        "run_id": config.run_id,
    }

    adapter = make_adapter(config)
    inflight: dict[str, int] = {}
    latencies_ms: list[float] = []
    received_ids: set[str] = set()
    receive_lock = threading.Lock()

    def _on_message(raw: bytes) -> None:
        nonlocal latencies_ms
        try:
            item = json.loads(raw.decode("utf-8"))
            event_id = item["id"]
            sent_ns = int(item["sent_ns"])
        except (ValueError, KeyError, TypeError, AttributeError):
            return

        recv_ns = _now_ns()
        latency_ms = (recv_ns - sent_ns) / 1_000_000
        with receive_lock:
            if event_id not in inflight:
                return
            if event_id in received_ids:
                return
            received_ids.add(event_id)
            latencies_ms.append(latency_ms)
            received_counter.add(1, labels)
            latency_hist.record(latency_ms, labels)

    adapter.connect()
    adapter.prepare()
    adapter.start_consumer(_on_message)
    if not adapter.wait_until_ready(timeout_seconds=10.0):
        raise RuntimeError(f"{config.broker} consumer was not ready before publish")

    payload_chunk = "x" * max(0, config.message_size - 120)
    start = time.monotonic()
    for idx in range(config.target_messages):
        event_id = f"{config.run_id}-{idx}"
        envelope = {"id": event_id, "sent_ns": _now_ns(), "payload": payload_chunk}
        body = json.dumps(envelope).encode("utf-8")
        inflight[event_id] = envelope["sent_ns"]
        adapter.publish(body)
        sent_counter.add(1, labels)

    adapter.after_publish()

    deadline = start + config.timeout_seconds
    while time.monotonic() < deadline:
        with receive_lock:
            if len(received_ids) >= config.target_messages:
                break
        time.sleep(0.1)

    adapter.stop()
    duration_seconds = time.monotonic() - start
    run_duration_hist.record(duration_seconds, labels)

    delivered = len(received_ids)
    throughput = delivered / duration_seconds if duration_seconds > 0 else 0.0
    sorted_latencies = sorted(latencies_ms)

    def _pct(value: float) -> float:
        if not sorted_latencies:
            return 0.0
        idx = int((len(sorted_latencies) - 1) * value)
        return round(sorted_latencies[idx], 3)

    return {
        "run_id": config.run_id,
        "broker": config.broker,
        "scenario": config.scenario,
        "sent": config.target_messages,
        "received": delivered,
        "delivery_ratio": round((delivered / config.target_messages) if config.target_messages else 0.0, 4),
        "throughput_msg_per_sec": round(throughput, 2),
        "duration_seconds": round(duration_seconds, 3),
        "latency_ms": {
            "p50": _pct(0.50),
            "p95": _pct(0.95),
            "p99": _pct(0.99),
            "max": round(max(sorted_latencies), 3) if sorted_latencies else 0.0,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream broker end-to-end benchmark")
    parser.add_argument("--broker", choices=["kafka", "rabbitmq", "mqtt"], required=True)
    parser.add_argument("--scenario", default=os.getenv("BENCHMARK_SCENARIO", "baseline"))
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run benchmark repeatedly until interrupted (for live Grafana streaming).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=float(os.getenv("BENCHMARK_SLEEP_SECONDS", "1.0")),
        help="Pause between benchmark loops in continuous mode.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = BenchmarkConfig.from_env(broker=args.broker, scenario=args.scenario)
    provider = setup_meter_provider(
        service_name="stream-benchmark-runner", otlp_endpoint=config.otlp_endpoint
    )
    try:
        if args.continuous:
            while True:
                result = run_benchmark(config)
                print(json.dumps(result, indent=2), flush=True)
                time.sleep(max(0.0, args.sleep_seconds))
        else:
            result = run_benchmark(config)
            print(json.dumps(result, indent=2))
    finally:
        force_flush = getattr(provider, "force_flush", None)
        if callable(force_flush):
            force_flush()
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()


if __name__ == "__main__":
    main()
