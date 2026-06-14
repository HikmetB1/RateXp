# Deploying RateXp to Azure

One Terraform stack builds everything: two web apps (`core` + `app`), a PostgreSQL
server, and a container registry. The apps reach the database passwordlessly
(each uses its Managed Identity + a Microsoft Entra token).

## Prerequisites

- **Azure CLI** — run `az login` first
- **Terraform** ≥ 1.5
- **Docker**

## Deploy (first time)

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # then set subscription_id

# 1. Create all Azure resources
terraform init
terraform apply

# 2. Build + push the two images
az acr login --name "$(terraform output -raw acr_name)"
docker build -t "$(terraform output -raw core_image)" --build-arg EXTRAS=entra ../core
docker push "$(terraform output -raw core_image)"
docker build -t "$(terraform output -raw app_image)" --build-arg EXTRAS=entra -f ../app/Dockerfile ../app
docker push "$(terraform output -raw app_image)"

# 3. Give each app its database role (run as the Entra admin)
#    First edit grant-db-access.sql: replace CORE_NAME / CORE_OBJECT_ID / APP_NAME /
#    APP_OBJECT_ID (see `terraform output grant_db_access_hint`), then split it at the
#    two markers into Part A and Part B.
TOKEN="$(az account get-access-token --resource https://ossrdbms-aad.database.windows.net --query accessToken -o tsv)"
HOST="$(terraform output -raw postgres_fqdn)"
ADMIN="<entra_admin_principal_name from terraform.tfvars>"
PGPASSWORD="$TOKEN" psql "host=$HOST dbname=postgres user=$ADMIN sslmode=require" -f partA.sql
PGPASSWORD="$TOKEN" psql "host=$HOST dbname=ratexp   user=$ADMIN sslmode=require" -f partB.sql

# 4. Start the apps so they pull their images (use stop/start, not restart)
RG="$(terraform output -raw resource_group)"
for app in "$(terraform output -raw core_name)" "$(terraform output -raw app_name)"; do
  az webapp stop  --name "$app" --resource-group "$RG"
  az webapp start --name "$app" --resource-group "$RG"
done
```

Dashboard: `terraform output -raw app_url`. Point your skills at `terraform output -raw core_url`.

> The DB firewall must allow your IP (Portal → PostgreSQL server → Networking), or
> run the `psql` step from Azure Cloud Shell.

## Ship a code change

Rebuild + push that image, then **stop/start** the app — a plain `restart` will *not*
re-pull `:latest`:

```bash
docker build -t "$(terraform output -raw app_image)" --build-arg EXTRAS=entra -f ../app/Dockerfile ../app
docker push "$(terraform output -raw app_image)"
RG="$(terraform output -raw resource_group)"; APP="$(terraform output -raw app_name)"
az webapp stop --name "$APP" --resource-group "$RG"
az webapp start --name "$APP" --resource-group "$RG"
```

## Optional features

Set in `terraform.tfvars`, then `terraform apply` again:

- `enable_redaction = true` — Azure AI Language masks PII in stored transcripts.
  Build core with `--build-arg EXTRAS="entra redaction"`.
- `enable_seeder = true` — an Azure Function + Azure OpenAI that seeds demo
  feedback. Push its image (`seeder_image`) and stop/start `seeder_name` too.

## What's in this folder

| File | What it's for |
|------|---------------|
| `main.tf` | All the Azure resources |
| `variables.tf` | Tunables — feature toggles, SKUs, region |
| `outputs.tf` | Names, URLs, and image refs the commands above read |
| `terraform.tfvars` / `.example` | Your settings (subscription id, toggles) |
| `dev.tfvars` | A second, parallel `dev` environment |
| `grant-db-access.sql` | The Part A / Part B database role grants |
| `providers.tf`, `versions.tf` | Provider and version pins |
| `terraform.tfstate*` | Terraform state — managed by Terraform, don't edit by hand |
