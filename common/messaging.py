"""RabbitMQ topology + publish helpers.

Topology:
  video_tasks              main work queue (quorum semantics not needed locally)
  video_tasks.retry.<ttl>  parking queues; expired messages dead-letter back
                           into video_tasks (escalating TTL = backoff)
  video_tasks.dlq          messages that exhausted all retries
"""
from __future__ import annotations

import json

import pika

MAIN_QUEUE = "video_tasks"
DLQ = "video_tasks.dlq"
RETRY_TTLS_MS = {"10s": 10_000, "30s": 30_000, "60s": 60_000}


def retry_queue_name(suffix: str) -> str:
    return f"{MAIN_QUEUE}.retry.{suffix}"


def declare_topology(channel) -> None:
    channel.queue_declare(queue=MAIN_QUEUE, durable=True)
    channel.queue_declare(queue=DLQ, durable=True)
    for suffix, ttl in RETRY_TTLS_MS.items():
        channel.queue_declare(
            queue=retry_queue_name(suffix),
            durable=True,
            arguments={
                "x-message-ttl": ttl,
                "x-dead-letter-exchange": "",        # default exchange
                "x-dead-letter-routing-key": MAIN_QUEUE,
            },
        )


def publish(channel, queue: str, message: dict) -> None:
    channel.basic_publish(
        exchange="",
        routing_key=queue,
        body=json.dumps(message).encode(),
        properties=pika.BasicProperties(
            delivery_mode=pika.DeliveryMode.Persistent,
            content_type="application/json",
        ),
    )


def connect(url: str) -> pika.BlockingConnection:
    return pika.BlockingConnection(pika.URLParameters(url))
