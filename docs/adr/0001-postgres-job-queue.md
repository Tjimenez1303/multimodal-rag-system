# 0001. PostgreSQL as the ingestion job queue

- **Status**: Accepted
- **Date**: 2026-09-29
- **Deciders**: project maintainer

## Context and problem statement

Processing a technical manual takes minutes, so uploads return at once and the work
happens in the background. Users need to follow each job, and a job interrupted by a
crash or a restart must start again automatically, at most three times, without ever
running on two workers at the same time. The system must also grow by adding workers,
and keep a single start command.

Where should jobs wait, and who guarantees that an interrupted job is picked up again
exactly once?

## Decision drivers

- An interrupted job must come back promptly, with its attempt counted.
- Two workers must never process the same job at the same time.
- Job status must survive restarts and be readable by the API.
- One more service to run is a cost for every reviewer and every deployment.

## Considered options

1. PostgreSQL as both the job store and the queue.
2. Celery with Redis.
3. Celery with RabbitMQ quorum queues.
4. A PostgreSQL queue library (procrastinate or pgqueuer).

## Decision outcome

Chosen option: **PostgreSQL as both the job store and the queue**, because it is the
only option that meets every driver on its own and adds no service.

A worker takes a job for a limited time (a lease) and renews it while it works. If the
worker disappears, the lease runs out and another worker takes the job as its next
attempt, while users keep seeing it as processing. Every write about a job proves that
the worker still holds the current lease, so a worker that was replaced can no longer
change the job. After the last allowed attempt the job fails with a reason that says it
was interrupted repeatedly.

### Consequences

- Good, because an upload stores the document and its job in the same database, so they
  can never disagree.
- Good, because there is nothing new to install or operate, and job status is one query
  away.
- Good, because adding workers needs no configuration, and a crash is recovered within
  one lease period (90 seconds by default).
- Bad, because the queue logic (claim, lease renewal, recovery) is about 150 lines the
  project owns and tests itself.
- Neutral, because PostgreSQL queues show their limits at millions of jobs per day, far
  above the expected load of this system.

## Annex: technical evidence

### Mechanism

Workers claim with `SELECT … FOR UPDATE SKIP LOCKED`, increment `attempt` and set a
`lease_token` with `lease_expires_at`, both measured on the database clock (`now()`), as
River does, so clock skew between workers cannot expire a lease early. A heartbeat
renews the lease every `HEARTBEAT_SECONDS` (30). A `processing` job whose lease expired
is claimable again, and the claim that would exceed `MAX_ATTEMPTS` fails it with
`interrupted_repeatedly`. Every job write is conditioned on the current token, which
acts as a fencing token. Workers wake up through `LISTEN/NOTIFY` with a `POLL_SECONDS`
fallback, as Prefect's Postgres listener and procrastinate do.

### Celery with Redis

Kombu emulates acknowledgements with a fixed `visibility_timeout` (one hour by default)
that is never extended while a task runs. A task that runs longer is delivered again and
runs concurrently on another worker, which the Celery documentation warns can repeat
"again, and again in a loop". After a container crash the task only returns once the
timeout elapses. Celery counts no crash redeliveries, only a boolean `redelivered`, and
`task_reject_on_worker_lost` can cause message loops. No fix exists in Celery 5.6.3 or
Kombu 5.7.0a1. Meeting the spec would still need the lease, the counter and the fencing
in PostgreSQL, plus Redis.

### Celery with RabbitMQ quorum queues

Redelivers at once on connection loss and counts deliveries, but `consumer_timeout` (30
minutes by default) must be raised for long jobs, fencing is still needed, and RabbitMQ
adds a service.

### procrastinate and pgqueuer

procrastinate needs a periodic task to retry stalled jobs and has an open issue where a
stale worker can write to a job another worker took over (#1633).

### Measured recovery

On the reference machine a worker killed with SIGKILL during a job was replaced, and the
new worker claimed the job 78 seconds later as attempt 2, within the 90-second lease.
The job completed with the same 309 retrieval units and 1,806 elements as three clean
runs, and no hidden or duplicate points. The automated test
`backend/tests/integration/test_crash_recovery.py` repeats this with a real worker
process on every CI run.

### Sources

- https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html
- https://docs.celeryq.dev/en/stable/userguide/tasks.html
- https://github.com/celery/kombu/blob/v5.6.2/kombu/transport/redis.py
- https://github.com/celery/celery/issues/5935
- https://github.com/celery/celery/discussions/9963
- https://www.rabbitmq.com/docs/consumers
- https://www.rabbitmq.com/docs/quorum-queues
- https://github.com/procrastinate-org/procrastinate/issues/1633
- https://brandur.org/river
- https://www.postgresql.org/docs/current/sql-select.html
- https://rubyonrails.org/2024/11/7/rails-8-no-paas-required
- Full analysis: `specs/001-async-pdf-ingestion/research.md`, sections 2 and 15
