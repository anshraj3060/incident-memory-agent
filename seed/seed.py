"""Retain a small, deterministic set of synthetic incident reports."""
from datetime import date, timedelta
import json

from app.services import bank, memory_client

PATTERNS = [
    ('checkout-api', 'java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms\n at com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:196)', 'Unclosed connections in the order lookup path exhausted the PostgreSQL pool', ['Confirm active and idle connections in pg_stat_activity', 'Roll back the leaking release', 'Verify pool utilization and error rate recover'], 'db-pool-exhaustion', 24),
    ('catalog-api', 'redis.exceptions.ResponseError: OOM command not allowed when used memory > maxmemory\n at redis/client.py:1255', 'Cache maxmemory was reached with noeviction policy', ['Inspect Redis memory and eviction policy', 'Remove stale cache keys and adjust TTLs', 'Verify memory and cache hit rate'], 'redis-memory-pressure', 31),
    ('payments-api', 'HTTP 503 upstream connect error; deployment payments-v42\n at gateway.Proxy.forward(proxy.go:184)', 'A bad deployment shipped an incompatible upstream configuration', ['Compare errors to deployment timeline', 'Roll back to the last healthy release', 'Confirm success rate and investigate the configuration'], 'deployment-rollback', 13),
    ('edge-gateway', 'tls: failed to verify certificate: x509: certificate has expired or is not yet valid\n at tls/handshake_client.go:1143', 'The gateway TLS certificate expired after renewal failed', ['Check certificate expiry and renewal controller', 'Renew and deploy the certificate', 'Verify the complete chain and expiry'], 'tls-expiry', 37),
    ('events-worker', 'WARN Consumer group events lag=98342; CommitFailedException: consumer is not part of an active group\n at org.apache.kafka.clients.consumer.internals.ConsumerCoordinator.commitOffsetsSync(ConsumerCoordinator.java:1035)', 'A slow downstream call caused consumer poll timeouts and rebalances', ['Inspect consumer lag and rebalance metrics', 'Mitigate the slow downstream dependency', 'Restart stuck consumers gradually and verify lag falls'], 'kafka-consumer-lag', 46),
    ('image-processor', 'kubelet: Container image-processor terminated Reason: OOMKilled Exit Code: 137\n at worker/render.py:88', 'A large image batch exceeded the worker memory limit', ['Inspect memory and batch size', 'Reduce batch concurrency and restart affected pods', 'Verify memory stays below the limit'], 'oom-worker', 21),
]


def incidents():
    records = []
    for i in range(25):
        service, error, cause, steps, runbook, minutes = PATTERNS[i % len(PATTERNS)]
        record = {'incident_id': f'SYN-{i+1:03}', 'synthetic': True, 'service': service,
                  'error_log': error, 'severity': 'SEV1' if i % 4 == 0 else 'SEV2',
                  'root_cause': cause, 'resolution_steps': steps, 'runbook': runbook,
                  'time_to_resolve_minutes': minutes + (i % 5) * 3,
                  'date': (date(2025, 1, 8) + timedelta(days=i * 13)).isoformat(),
                  'outcome': 'worked; service recovered'}
        records.append(record)
    return records


def main():
    client = memory_client()
    rows = incidents()
    for start in range(0, len(rows), 5):
        items = [{'content': 'Synthetic historical incident: ' + json.dumps(row), 'context': 'Synthetic incident report'} for row in rows[start:start+5]]
        client.retain_batch(bank_id=bank(), items=items, retain_async=False)
        print(f'Retained {start + len(items)}/{len(rows)}')
    print('Done. Re-running may create duplicate memories.')


if __name__ == '__main__':
    main()
