# Custom deploy: run your own RateXp

- [Deploy to Azure](#deploy-to-azure-from-zero-to-live)
  - [Before you start](#before-you-start-the-tools-you-need)
  - [Steps](#steps-deploy-in-five-steps)
  - [Optional extras](#optional-extras-set-in-terraformtfvars)
  - [Terraform and config.yaml](#terraform-and-configyaml-which-one-counts)

Instead of the hosted service, you can run your own copy of RateXp. Each cloud has its own
section on this page (now: Azure).

## Deploy to Azure: from zero to live

One Terraform stack creates all of RateXp on Azure:

- two web apps, `core` and `app`;
- a managed PostgreSQL server;
- a container registry for the images.

The `core` and `app` web apps sign in to the database through Microsoft Entra ID. You do
not keep a database password anywhere.

### Before you start: the tools you need

1. Install the Azure CLI.
2. Run `az login`.
3. Install Terraform.
4. Install Docker.
5. Install `psql`, the PostgreSQL client. Step 3 needs it.

### Steps: deploy in five steps

1. **Create the Azure resources.** In `infra/`, copy `terraform.tfvars.example` to
   `terraform.tfvars`:

   ```bash
   cd infra
   cp terraform.tfvars.example terraform.tfvars   # put your subscription_id in it
   ```

   Write your `subscription_id` in `terraform.tfvars`. Then run Terraform:

   ```bash
   terraform init && terraform apply
   ```

2. **Build the images. Then push them to the registry.** Run these commands in `infra/`:

   ```bash
   az acr login --name "$(terraform output -raw acr_name)"
   docker build -t "$(terraform output -raw core_image)" ../core && docker push "$(terraform output -raw core_image)"
   docker build -t "$(terraform output -raw app_image)" -f ../app/ratexp/Dockerfile --build-context dashboard=../core/modules/dashboard ../app/ratexp && docker push "$(terraform output -raw app_image)"
   ```

3. **Give the `core` and `app` web apps access to the database.** Run
   [`infra/grant-db-access.sql`](../infra/grant-db-access.sql) one time, as its header tells.
   Connect as the Entra admin of the server (by default, the account that ran
   `terraform apply`):

   1. In the Azure portal, add your IP address under **Networking** of the PostgreSQL server.
      Or run this step in Azure Cloud Shell.
   2. Get a database token:

      ```bash
      export PGPASSWORD="$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)"
      ```

   3. Connect with `psql`. For `user`, use `entra_admin_principal_name` (default
      `ratexp-deployer`). For `dbname`, use the database that the header names for each part:

      ```bash
      psql "host=$(terraform output -raw postgres_fqdn) user=ratexp-deployer dbname=postgres sslmode=require"
      ```

4. **Stop each web app. Then start it again.** This makes Azure pull the image that you
   pushed. Do not use `az webapp restart`. It continues to use the old cached image.

   ```bash
   for name in "$(terraform output -raw core_name)" "$(terraform output -raw app_name)"; do
     az webapp stop --resource-group "$(terraform output -raw resource_group)" --name "$name"
     az webapp start --resource-group "$(terraform output -raw resource_group)" --name "$name"
   done
   ```

5. **Install RateXp from your own core.** Run the
   [Quick start](../README.md#quick-start-install-in-one-command) line with your core's URL in
   place of `https://ratexp-core.azurewebsites.net`:

   ```bash
   curl -fsSL "$(terraform output -raw core_url)/install.sh" | bash -s -- install claude
   ```

### Optional extras: set in terraform.tfvars

[`infra/variables.tf`](../infra/variables.tf) describes each optional value:

- `enable_*`
- `phoenix_*`
- `bluebox_*`
- `dynatrace_*`

After you change a value:

- **Every value:** run `terraform apply` again.
- **`enable_seeder`:** then also do these steps:
  1. Build `seeder_image` from `../seeder`.
  2. Push it, as in step 2.
  3. Stop and start the seeder (`seeder_name`) with `az functionapp stop` and
     `az functionapp start`.

### Terraform and config.yaml: which one counts

Terraform creates the Azure parts. It gives core and the app their endpoints and tokens. A
`config.yaml` switches each part on and selects the adapter. Thus, set both. If both set the
same thing, the Terraform value wins (now only the redaction provider).

- **Redaction:**
  - `redaction.enabled` in `core/config.yaml` switches redaction on or off.
  - `redaction_provider` in `terraform.tfvars` selects the provider. It wins over
    `redaction.provider` in `core/config.yaml`.
  - For the `azure` provider, put `terraform output -raw language_endpoint` in
    `redaction.azure_endpoint` in `core/config.yaml`.
- **Labeling:**
  - `enable_labeling` gives core the endpoint of the model.
  - `labeling.enabled` in `core/config.yaml` must also be `true`.
  - `labeling.deployment` in `core/config.yaml` must be equal to `labeling_model`.
- **Destinations (Dynatrace, Phoenix, Bluebox):**
  - `write_adapters.<name>.enabled` in `core/config.yaml` switches each destination on.
  - The `dynatrace_*`, `phoenix_*` and `bluebox_*` values give it its endpoint and token.
  - If a destination is on but has no values, core skips it and logs this.
- **Read source of the app:**
  - `read_adapters` in `app/ratexp/config.yaml` selects the one read source.
  - `dynatrace_query_url` and the Dynatrace token only give its credentials.
- **After a change:**
  - In `terraform.tfvars`: run `terraform apply` again.
  - In a `config.yaml`: the image contains this file. Build and push the image again (step 2).
    Then stop and start the web app (step 4).
