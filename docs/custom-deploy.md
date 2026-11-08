# Custom deploy: run your own RateXp

- [Deploy to Azure](#deploy-to-azure-from-zero-to-live)
  - [Before you start](#before-you-start-the-tools-you-need)
  - [Steps](#steps-deploy-ratexp-to-azure)
  - [Optional extras](#optional-extras-set-in-terraformtfvars)
  - [Terraform and config.yaml](#terraform-and-configyaml-which-one-counts)
  - [Destinations](#destinations-where-core-writes-the-feedback)

You can run your own copy of RateXp in place of the hosted service. This page has one section
for each cloud (now: Azure).

## Deploy to Azure: from zero to live

One Terraform stack creates all of RateXp on Azure:

- **Web apps:** two web apps, `core` and `app`.
- **Database:** a managed PostgreSQL server.
- **Registry:** a container registry for the images.

The `core` and `app` web apps sign in to the database through Microsoft Entra ID. Thus, you do
not keep a database password anywhere.

### Before you start: the tools you need

1. Install the Azure CLI.
2. Run `az login`.
3. Install Terraform.
4. Install Docker.
5. Install `psql`, the PostgreSQL client. Step 3 uses `psql`.

### Steps: deploy RateXp to Azure

1. **Create the Azure resources.** In `infra/`, copy `terraform.tfvars.example` to
   `terraform.tfvars`:

   ```bash
   cd infra
   cp terraform.tfvars.example terraform.tfvars
   ```

   Write your `subscription_id` in `terraform.tfvars`. Then run Terraform:

   ```bash
   terraform init && terraform apply
   ```

2. **Build the images. Then push the images to the registry.** Run these commands in `infra/`:

   ```bash
   az acr login --name "$(terraform output -raw acr_name)"
   docker build -t "$(terraform output -raw core_image)" --build-context repo=.. ../core && docker push "$(terraform output -raw core_image)"
   docker build -t "$(terraform output -raw app_image)" -f ../app/ratexp/Dockerfile --build-context dashboard=../core/modules/dashboard ../app/ratexp && docker push "$(terraform output -raw app_image)"
   ```

3. **Give the `core` and `app` web apps access to the database.** Run
   [`infra/grant-db-access.sql`](../infra/grant-db-access.sql) one time, as the header of the
   file tells. Connect as the Entra admin of the server (by default, the account that ran
   `terraform apply`):

   1. In the Azure portal, add your IP address under **Networking** of the PostgreSQL server.
      Or, in place of the IP address, run step 3 in Azure Cloud Shell.
   2. Get a database token:

      ```bash
      export PGPASSWORD="$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)"
      ```

   3. Connect with `psql`. For `user`, use `entra_admin_principal_name` (default
      `ratexp-deployer`). For `dbname`, use the database that the header names for each part:

      ```bash
      psql "host=$(terraform output -raw postgres_fqdn) user=ratexp-deployer dbname=postgres sslmode=require"
      ```

4. **Stop each web app. Then start the web app again.** Azure then pulls the image that you
   pushed. Do not use `az webapp restart`, because `az webapp restart` continues to use the
   old cached image.

   ```bash
   for name in "$(terraform output -raw core_name)" "$(terraform output -raw app_name)"; do
     az webapp stop --resource-group "$(terraform output -raw resource_group)" --name "$name"
     az webapp start --resource-group "$(terraform output -raw resource_group)" --name "$name"
   done
   ```

5. **Install RateXp from your own core.** Run the install command from
   [Quick start](../README.md#quick-start-install-ratexp), with the URL of your core in place of
   `https://ratexp-core.azurewebsites.net`:

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

- **Each value:** Run `terraform apply` again.
- **`enable_seeder`:** Also do these steps:
  1. Build `seeder_image` from `../seeder`.
  2. Push `seeder_image`, as in step 2.
  3. Stop the seeder (`seeder_name`) with `az functionapp stop`. Then start the seeder with
     `az functionapp start`.

### Terraform and config.yaml: which one counts

- **Terraform:** Terraform creates the Azure parts, and gives core and the app their endpoints
  and tokens.
- **config.yaml:** A `config.yaml` switches each part on and selects the adapter.
- **Both:** Thus, set Terraform and `config.yaml`. If both set the same value, the Terraform
  value wins (now only the redaction provider).

Each part:

- **Redaction:**
  - `redaction.enabled` in `core/config.yaml` switches redaction on or off.
  - `redaction_provider` in `terraform.tfvars` selects the provider. `redaction_provider` wins
    over `redaction.provider` in `core/config.yaml`.
  - For the `azure` provider, put the output of `terraform output -raw language_endpoint` in
    `redaction.azure_endpoint` in `core/config.yaml`.
- **Labeling:**
  - `enable_labeling` gives core the endpoint of the model.
  - `labeling.enabled` in `core/config.yaml` must also be `true`.
  - `labeling.deployment` in `core/config.yaml` must be the same as `labeling_model`.
- **Destinations (Dynatrace, Phoenix, Bluebox):**
  - `write_adapters.<name>.enabled` in `core/config.yaml` switches each destination on.
  - The `dynatrace_*`, `phoenix_*` and `bluebox_*` values give each destination its endpoint
    and its token.
  - If a destination is on but has no values, core skips the destination and writes a log
    entry.
  - For the list of write adapters, see
    [Destinations](#destinations-where-core-writes-the-feedback).
- **Read source of the app:**
  - `read_adapters` in `app/ratexp/config.yaml` selects the one read source.
  - `dynatrace_query_url` and the Dynatrace token give only the credentials of the read source.
- **After a change:**
  - **In `terraform.tfvars`:** Run `terraform apply` again.
  - **In a `config.yaml`:** The image contains the `config.yaml` file. Build and push the image
    again (step 2). Then stop and start the web app (step 4).

<!-- shared ../README.md destinations -->
### Destinations: where core writes the feedback

See [Destinations](../README.md#destinations-where-core-writes-the-feedback) in the README.
<!-- /shared -->
