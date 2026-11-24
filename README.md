# Badger & Dodo – Sample Cloud Deployment (B9MG210 CA1)

The AWS tier of the cloud strategy for **Badger & Dodo**, the specialty coffee
roaster in Fermoy, Co. Cork: a containerised wholesale partner portal where
partner cafés place one-off or weekly standing orders, and the roastery sees a
combined roast plan and dispatch sheet.

> Student project. Badger & Dodo is a real business, but this portal is not an
> official Badger & Dodo service and the company was not consulted. Product
> names, prices and roast days in the app are illustrative.

```
Internet ──► Application Load Balancer (2 public subnets, 2 AZs)
                 │  HTTP :80, health check /health
                 ▼
          EC2 Auto Scaling group (2–4 × t3.micro, Amazon Linux 2023)
          each instance runs two Docker containers:
            proxy (nginx:80) ──► web (Flask + gunicorn :8000)
                 │                         │
                 │ MySQL :3306             │ PutObject
                 ▼                         ▼
          Amazon RDS for MySQL       Amazon S3 bucket
          (private subnets,          (versioned, encrypted,
           encrypted, Multi-AZ opt.)  roast + dispatch CSVs)
          credentials ◄── AWS Secrets Manager (generated at deploy time)
```

| Characteristic | How it is achieved |
| --- | --- |
| High availability | ALB and instances span two Availability Zones; ASG replaces failed instances (ELB health checks) |
| Elasticity | Target-tracking policy keeps average CPU at 50%, scaling 2 → 4 instances |
| Security | Security-group chaining (ALB → app → DB), DB in private subnets with no internet route, IMDSv2 only, secret generated in Secrets Manager, S3 public access blocked, encryption at rest |
| Infrastructure as code | Everything in `infra/badger-dodo-stack.yaml` (CloudFormation) |
| Containers | App and proxy run as separate containers on a Docker network on each VM |
| CI | GitHub Actions runs unit tests, `cfn-lint` and a Docker build on every push |

## Repository layout

| Path | Purpose |
| --- | --- |
| `app/` | Flask application, Dockerfile, unit tests |
| `deploy/` | nginx config used on EC2; `docker-compose.yml` for local development |
| `infra/badger-dodo-stack.yaml` | CloudFormation template for the whole stack |
| `scripts/deploy.sh` | One-command deploy from the Learner Lab terminal |
| `scripts/demo_load.sh` | Shows load balancing, or drives CPU load to trigger scale-out |

## Deploy (AWS Academy Learner Lab)

The Learner Lab only allows `us-east-1` and `us-west-2`, so the demo runs in
`us-east-1`. Production would use `eu-west-1` (Dublin); the template is
region-independent.

1. Push this repository to GitHub (public, or create a read-only token for the `GitToken` parameter).
2. Start the Learner Lab and open the AWS Console.
3. **Either** CloudFormation → Create stack → Upload `infra/badger-dodo-stack.yaml`
   → set `GitRepoUrl` → leave the other defaults → Create.
   **Or**, from the Learner Lab terminal:
   ```bash
   git clone https://github.com/<owner>/badger-dodo-cloud.git && cd badger-dodo-cloud
   bash scripts/deploy.sh https://github.com/<owner>/badger-dodo-cloud.git us-east-1
   ```
4. Wait about 15 minutes (RDS takes the longest). Open the `PortalUrl` output.

Delete the stack after the demo to save lab credit (empty the S3 bucket first).

## Demo script (Week 12)

1. Open `PortalUrl`; refresh. The header badge alternates between two instance IDs in different AZs → **load balancing across AZs**.
2. Place a one-off order and a weekly standing order for a partner café; both appear in *Recent orders* with the instance that saved them, and in the *Roast plan* → **shared state in RDS**.
3. Click *Export roast and dispatch sheet to S3*; show the CSV in the S3 console → **app ↔ S3 integration via the instance role**.
4. Terminate one instance in the EC2 console; the site stays up, and the ASG launches a replacement → **self-healing**.
5. Run `bash scripts/demo_load.sh <PortalUrl> stress`; watch the ASG *Activity* tab add instances → **auto scaling**.
6. Show the CloudFormation template and the GitHub Actions run → **IaC and CI**.

## Run locally

```bash
pip install -r app/requirements.txt pytest
pytest -q app/tests                      # SQLite, no AWS needed
docker compose -f deploy/docker-compose.yml up --build   # web + nginx + MySQL on :8080
```

## Known simplifications (lab vs production)

- App instances sit in public subnets (inbound only from the ALB security group) to avoid NAT Gateway cost in the lab. Production: private subnets with a NAT Gateway or VPC endpoints.
- HTTP only; production adds an ACM certificate and an HTTPS listener, plus partner sign-in (for example Amazon Cognito).
- RDS is single-AZ by default in the lab (`MultiAZDatabase=true` for production).
- The `/stress` endpoint exists only to demonstrate scaling and would be disabled in production.

## Attribution

Initial code generated with Claude Opus 5.5 (Anthropic) on 12 Nov 2026 for a
fictional business, then adapted to Badger & Dodo with Claude Opus 5.5 on
24 Nov 2026 (partner orders, delivery county, weekly standing orders and a
dispatch summary in the S3 export). Reviewed, tested and modified by the group
(see the report, Appendix A, and the commit history). Third-party components:
Flask (BSD-3), SQLAlchemy (MIT), PyMySQL (MIT), gunicorn (MIT), boto3
(Apache-2.0), nginx (BSD-2), MySQL image (GPLv2) for local development only.
