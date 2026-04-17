# EDISS A3 — Book store on EKS

Five microservices:

| # | Service            | Replicas | Liveness | K8s service type |
|---|--------------------|----------|----------|------------------|
| 1 | `book-service`     | 1        | `/status`| ClusterIP        |
| 2 | `customer-service` | 2        | `/status`| ClusterIP        |
| 3 | `web-bff`          | 2        | `/status`| LoadBalancer     |
| 4 | `mobile-bff`       | 2        | `/status`| LoadBalancer     |
| 5 | `crm-service`      | 1        | —        | (no Service)     |

Supporting infra:

* `internal-gateway` — in-cluster nginx that routes `/books/**` and `/customers/**` to the respective backend service (keeps the BFFs unaware of individual backend hosts).
* Aurora MySQL cluster on RDS, two logical databases: `books` and `customers` (DB-per-microservice).
* Kafka cluster (provided) — customer-service produces to `<ANDREW_ID>.customer.evt`, CRM consumes it.
* External recommendation engine (provided) — base URL is injected via the `RECOMMENDATION_URL` env var.

All application pods live in the `bookstore-ns` namespace.

## Repository layout

```
book-service/        Flask app, circuit breaker, k8s/ manifests
customer-service/    Flask app, Kafka producer, k8s/ manifests
web-bff/             Flask BFF (web), k8s/ manifests (LoadBalancer)
mobile-bff/          Flask BFF (mobile), k8s/ manifests (LoadBalancer)
crm-service/         Kafka consumer + SMTP sender, k8s/ manifests
internal-gateway/    nginx routing manifests
k8s/                 Namespace + Secret templates (DB, Kafka, SMTP)
CF-A3-cmu.yml        CloudFormation for VPC + EKS + RDS
url.txt              Submission file
```

## Task coverage

* **Task 1 — EKS.** `kind: Deployment` and `kind: Service` files per microservice live under each service's `k8s/` directory. All use `imagePullPolicy: Always`. REST services declare an HTTP `livenessProbe` on `/status`. The book-service `Deployment` mounts an `emptyDir` volume at `/var/cb` to persist circuit-breaker state across container restarts.
* **Task 2 — `GET /books/{ISBN}/related-books`.** Implemented in `book-service/app.py`. Returns 200 with JSON array on success, 204 on empty recommendations, 504 on timeout (closed circuit), 503 when the circuit is open.
* **Task 3 — Circuit breaker.** `book-service/helpers/circuit_breaker.py`. 3 s HTTP timeout, opens on the first timeout/failure, stays open for 60 s, then attempts a single trial request; if it fails the timer is restarted and the caller gets 503, if it succeeds the circuit closes again. State is a JSON file on the mounted `emptyDir` volume (per-pod). Book service is deployed with `replicas: 1` so behavior is deterministic across requests.
* **Task 4 — Async CRM with Kafka.** `customer-service` publishes the created-customer payload (same JSON as the REST response) to `<ANDREW_ID>.customer.evt` after a successful `POST /customers`. `crm-service` consumes that topic and sends an email (`Subject: Activate your book store account`) via SMTP.
* **Task 5 — DB per microservice.** Customer service uses database `customers`, book service uses `books`. Both live on the same RDS Aurora MySQL cluster. Each service is the only component that connects to its database.

## Local development (docker-compose)

```bash
# One-time
cp .env.example .env   # fill in ANDREW_ID, SMTP_*, GEMINI_API_KEY if used
docker compose -f docker-compose.a3.yml up --build
```

Endpoints exposed on `localhost`:

* Web BFF  → <http://localhost:8080>
* Mobile BFF → <http://localhost:8081>
* Book service direct → <http://localhost:3002>
* Customer service direct → <http://localhost:3001>
* Recommendation engine (local) → <http://localhost:8088/swagger-ui.html>

To test the circuit breaker locally, stop the `recommendations` service and start it again with `--delay=10000` (see docker-compose override or `docker run pmerson/book-recommendations-ms --delay=10000`).

## Deploying to EKS

1. **Provision infra.** Create the CloudFormation stack from `CF-A3-cmu.yml`.
2. **Configure kubectl.**
   ```bash
   aws eks update-kubeconfig --region us-east-1 --name <cluster-name>
   kubectl get nodes
   ```
3. **Create databases on the RDS cluster.**
   ```sql
   CREATE DATABASE books;
   CREATE DATABASE customers;
   ```
4. **Build and push the five images** (replace `REPLACE_ME` with your registry).
   ```bash
   for svc in book-service customer-service web-bff mobile-bff crm-service; do
     docker build -t REPLACE_ME/$svc:latest $svc
     docker push REPLACE_ME/$svc:latest
   done
   ```
   Update each `k8s/deployment.yaml` `image:` field to match.
5. **Apply manifests.**
   ```bash
   kubectl apply -f k8s/00-namespace.yaml

   # Copy the two example secrets, fill in real values, then:
   kubectl apply -f k8s/01-db-credentials.yaml
   kubectl apply -f k8s/02-kafka-config.yaml

   kubectl apply -f internal-gateway/k8s/
   kubectl apply -f book-service/k8s/
   kubectl apply -f customer-service/k8s/
   kubectl apply -f web-bff/k8s/
   kubectl apply -f mobile-bff/k8s/
   kubectl apply -f crm-service/k8s/
   ```
6. **Wait for ELBs** and grab the hostnames:
   ```bash
   kubectl -n bookstore-ns get svc web-bff mobile-bff
   ```
   Put those hostnames into `url.txt` (along with your Andrew ID and email).

## Environment variables

### Shared

| Name                      | Where     | Notes |
|---------------------------|-----------|-------|
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD` | book + customer | Supplied via the `db-credentials` Secret |
| `DB_NAME`                 | book (`books`), customer (`customers`) | Fixed per service |
| `ANDREW_ID`               | customer + crm | Used to build the Kafka topic name |
| `KAFKA_BOOTSTRAP_SERVERS` | customer + crm | Comma-separated host:port list |
| `KAFKA_SECURITY_PROTOCOL` | customer + crm | `PLAINTEXT` (default) / `SASL_PLAINTEXT` / `SSL` / `SASL_SSL` |
| `KAFKA_SASL_USERNAME`, `KAFKA_SASL_PASSWORD`, `KAFKA_SASL_MECHANISM`, `KAFKA_SSL_CAFILE` | customer + crm | Only when SASL/SSL |

### book-service only

| Name                             | Purpose |
|----------------------------------|---------|
| `RECOMMENDATION_URL`             | Base URL of the external recommendation engine |
| `RECOMMENDATION_TIMEOUT_SECONDS` | HTTP timeout (default `3`) |
| `CB_STATE_PATH`                  | File path for circuit-breaker state (default `/var/cb/state.json`) |
| `CB_OPEN_WINDOW_SECONDS`         | Open window duration (default `60`) |
| `GEMINI_API_KEY` / `GEMINI_MODEL`| Optional — summary generator (unchanged from A2) |

### crm-service only

| Name             | Default              |
|------------------|----------------------|
| `SMTP_HOST`      | `smtp.gmail.com`     |
| `SMTP_PORT`      | `587`                |
| `SMTP_STARTTLS`  | `true`               |
| `SMTP_USE_SSL`   | `false`              |
| `SMTP_USERNAME`  | (required to auth)   |
| `SMTP_PASSWORD`  | (required to auth)   |
| `SMTP_FROM`      | falls back to `SMTP_USERNAME` |
