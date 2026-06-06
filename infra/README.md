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

docker build -t "$(terraform output -raw app_image)" --build-arg EXTRAS=entra -f ../app/Dockerfile ../app
docker push "$(terraform output -raw app_image)"
```

## 4. Grant each identity its database role

Open `grant-db-access.sql`, replace the four placeholders with the matching
`terraform output` values, then run it as the Entra admin (you):

```bash
PGPASSWORD="$(az account get-access-token \
  --resource https://ossrdbms-aad.database.windows.net \
  --query accessToken -o tsv)" \
psql "host=$(terraform output -raw postgres_fqdn) port=5432 dbname=ratexp \
  user=<your-entra-admin-name> sslmode=require" -f grant-db-access.sql
```

> Add your client IP as a firewall rule (Azure Portal → the PostgreSQL server →
> Networking) so `psql` can connect, or run the command from Azure Cloud Shell.

`core` gets read/write and owns the schema; `app` gets **read-only**.

## 5. Restart the web apps

```bash
RG="$(terraform output -raw resource_group)"
az webapp restart --name "$(terraform output -raw core_name)" --resource-group "$RG"
az webapp restart --name "$(terraform output -raw app_name)"  --resource-group "$RG"
```

Point your skills at `terraform output -raw core_url`; open the dashboard at
`terraform output -raw app_url`.

## What gets created

| Resource           | SKU              | Purpose                                  |
|--------------------|------------------|------------------------------------------|
| App Service Plan   | B1 (Linux)       | Shared by both web apps                   |
| Web App `core`     | —                | Public: snippet + feedback ingestion      |
| Web App `app`      | —                | Dashboard: read-only API + UI             |
| PostgreSQL Flexible| Burstable B1ms   | Feedback + transcript storage             |
| Container Registry | Basic            | Holds the `core` and `app` images         |
