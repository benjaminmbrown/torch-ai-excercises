import asyncio, json, logging
from aiokafka import AIOKafkaConsumer
from nexus.ingestion.pipeline import IngestionPipeline, RawEvent, IntSource

logger = logging.getLogger(__name__)
BATCH_SIZE    = 100   # Process up to 100 messages per commit cycle
BATCH_TIMEOUT = 1.0   # seconds


async def run_consumer(
    bootstrap_servers: str,
    topic: str,
    pipeline: IngestionPipeline,
) -> None:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        group_id="nexus-ingest-workers",
        enable_auto_commit=False,         # manual commit after successful persist
        auto_offset_reset="earliest",
        max_poll_records=BATCH_SIZE,
        value_deserializer=lambda b: json.loads(b.decode()),
        security_protocol="SSL",          # TLS 1.3 in transit
        ssl_cafile="/etc/nexus/kafka-ca.pem",
        ssl_certfile="/etc/nexus/kafka-client.pem",
        ssl_keyfile="/etc/nexus/kafka-client.key",
    )

    await consumer.start()
    logger.info("Kafka consumer started – topic=%s", topic)

    try:
        async for batch in consumer.getmany(
            timeout_ms=int(BATCH_TIMEOUT * 1000),
            max_records=BATCH_SIZE,
        ):
            tasks = []
            for tp, messages in batch.items():
                for msg in messages:
                    raw = RawEvent(
                        source_type=IntSource(msg.value["source_type"]),
                        source_id  =msg.value["source_id"],
                        raw_text   =msg.value["raw_text"],
                        metadata   =msg.value.get("metadata", {}),
                    )
                    tasks.append(pipeline.ingest(raw))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors  = [r for r in results if isinstance(r, Exception)]
            if errors:
                logger.error("%d ingest errors in batch", len(errors))
            # Commit only after all messages processed (at-least-once delivery)
            await consumer.commit()
    finally:
        await consumer.stop()
