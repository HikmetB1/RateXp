# Deploying RateXp to Azure

One Terraform stack provisions everything: two Linux web apps (`core` and
`app`), a PostgreSQL Flexible Server, and a container registry. Authentication to
the database is passwordless — each web app uses its Managed Identity and a
Microsoft Entra ID token, and password auth is disabled on the server.

All resources use the cheapest working SKUs (App Service **B1**, PostgreSQL
**Burstable B1ms**, ACR **Basic**).

## Prerequisites

- [Azure CLI](https://learn.microsoft.com/cli/azure/) — `az login`
- [Terraform](https://developer.hashicorp.com/terraform) ≥ 1.5
- Docker

## 1. Configure

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # then set subscription_id
```

## 2. (Re)create the infrastructure

To wipe a previous deployment first, run `terraform destroy`. Then:

```bash
terraform init
terraform apply
```

The deployer is set as the database's Entra administrator, so the next step can
create the per-app roles.

## 3. Build and push the images

```bash
az acr login --name "$(terraform output -raw acr_name)"

docker build -t "$(terraform output -raw core_image)" --build-arg EXTRAS=entra ../core
docker push "$(terraform output -raw core_image)"

# If you set enable_redaction = true, build core with the redaction extra too:
#   --build-arg EXTRAS="entra redaction"

docker build -t "$(terraform output -raw app_image)" --build-arg EXTRAS=entra -f ../app/Dockerfile ../app
docker push "$(terraform output -raw app_image)"
```

## 4. Grant each identity its database role

`grant-db-access.sql` has two parts: **Part A** creates the roles (run against the
`postgres` database, where the `pgaadauth_*` functions live — roles are
cluster-wide) and **Part B** grants privileges (run against the `ratexp`
database). Replace the four placeholders with the matching `terraform output`
values, split the file at the two markers, and run each part as the Entra admin
(you) — authenticating with an Entra token as the password:

```bash
TOKEN="$(az account get-access-token \
  --resource https://ossrdbms-aad.database.windows.net --query accessToken -o tsv)"
HOST="$(terraform output -raw postgres_fqdn)"
ADMIN="<your-entra-admin-name>"   # the principal_name from terraform.tfvars

# Part A → postgres database (create the roles)
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=postgres user=$ADMIN sslmode=require" -f partA.sql
# Part B → ratexp database (grant privileges)
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=ratexp user=$ADMIN sslmode=require" -f partB.sql
```

> Add your client IP as a firewall rule (Azure Portal → the PostgreSQL server →
> Networking) so `psql` can connect, or run the command from Azure Cloud Shell.
> No local `psql`? Run it in a container: `docker run --rm -e PGPASSWORD="$TOKEN"
> -v "$PWD":/sql postgres:16-alpine psql "host=$HOST …" -f /sql/partA.sql`.

`core` gets read/write and owns the schema; `app` gets **read-only**.

## 5. Restart the web apps

```bash
RG="$(terraform output -raw resource_group)"
az webapp restart --name "$(terraform output -raw core_name)" --resource-group "$RG"
az webapp restart --name "$(terraform output -raw app_name)"  --resource-group "$RG"
```

Point your skills at `terraform output -raw core_url`; open the dashboard at
`terraform output -raw app_url`.

## Optional: transcript PII redaction

Set `enable_redaction = true` in `terraform.tfvars` to provision an **Azure AI
Language** account (custom subdomain, key auth disabled) and grant core's Managed
Identity the **Cognitive Services User** role on it — so redaction is
**passwordless**, exactly like the database. No key is stored anywhere. The
toggle and endpoint live in `core/config.yaml` (`redaction.enabled` must be
`true` and `redaction.endpoint` must point at this account), so consented
transcripts are PII‑masked before they reach PostgreSQL (see `core/redact.py`).
Build the core image with the redaction extra (step 3 note above). The default
`language_sku_name` is the free `F0` tier (one per subscription); switch to `S`
for pay‑as‑you‑go.

## Multiple environments (e.g. dev)

The same stack can run a second, parallel environment alongside prod using a
**Terraform workspace** and the `environment` variable. Prod stays in the `default`
workspace untouched; the named environment gets its own state and clean,
suffix-free names (e.g. `rg-ratexp-dev`, `ratexp-dev-core`,
`https://ratexp-dev-app.azurewebsites.net`).

`infra/dev.tfvars` defines the `dev` environment. It reuses prod's Azure AI
**Language** account for redaction (the free F0 tier is one-per-subscription), so no
new Language resource is created — dev-core's identity is just granted access to the
existing one.

```bash
cd infra
terraform workspace new dev          # one-time: isolated state for dev
terraform apply -var-file=dev.tfvars # provisions everything in rg-ratexp-dev
```

Then run steps **3–5** above exactly as written — all the `terraform output`
commands read from the active (`dev`) workspace, so images push to the dev registry,
the database roles use the dev app names, and the restarts target the dev web apps.
Build the core image with the redaction extra (`--build-arg EXTRAS="entra redaction"`).

Switch back with `terraform workspace select default`. Running
`terraform plan` there should report **no changes** — proof that prod's names are
preserved.

## What gets created

| Resource           | SKU              | Purpose                                  |
|--------------------|------------------|------------------------------------------|
| App Service Plan   | B1 (Linux)       | Shared by both web apps                   |
| Web App `core`     | —                | Public: snippet + feedback ingestion      |
| Web App `app`      | —                | Dashboard: read-only API + UI             |
| PostgreSQL Flexible| Burstable B1ms   | Feedback + transcript storage             |
| Container Registry | Basic            | Holds the `core` and `app` images         |
| AI Language*       | F0               | PII redaction for transcripts (`enable_redaction`) |

\* Only when `enable_redaction = true`.
