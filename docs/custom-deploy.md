# Custom deploy: run your own RateXp

- [Deploy to Azure](#deploy-to-azure-from-zero-to-live)
  - [Before you start](#before-you-start-the-tools-you-need)
  - [Steps](#steps-deploy-ratexp-to-azure)
  - [Optional extras](#optional-extras-set-in-terraformtfvars)
  - [Terraform and config.yaml](#terraform-and-configyaml-which-one-counts)
  - [Dev environment](#dev-environment-test-a-change-before-prod)
  - [Destinations](#destinations-where-core-writes-the-feedback)

You can run your own copy of RateXp in place of the hosted service. This page has one section
for each cloud (now: Azure).

## Deploy to Azure: from zero to live

One Terraform stack creates all of RateXp on Azure:

- **Web apps:** two web apps, `core` and `app`.
- **Retention Function:** the `retention` Function deletes old ratings one time each hour.
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
   docker build -t "$(terraform output -raw retention_image)" -f ../core/Dockerfile.retention ../core && docker push "$(terraform output -raw retention_image)"
   ```

3. **Give the `core` and `app` web apps and the `retention` Function access to the database.**
   Run [`infra/grant-db-access.sql`](../infra/grant-db-access.sql) one time, as the header of
   the file tells. Connect as the Entra admin of the server (by default, the account that ran
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

   - **Retention grant:** The last statement of Part B gives the `retention` Function access to
     the tables `feedback` and `transcript`. The `core` web app makes the tables at its first
     rating. Thus, run the last statement of Part B again after the first rating.

4. **Stop each web app and the `retention` Function. Then start each web app and the
   `retention` Function again.** Azure then pulls the images that you pushed. Do not use `az webapp restart`, because
   `az webapp restart` continues to use the old cached image.

   ```bash
   for name in "$(terraform output -raw core_name)" "$(terraform output -raw app_name)"; do
     az webapp stop --resource-group "$(terraform output -raw resource_group)" --name "$name"
     az webapp start --resource-group "$(terraform output -raw resource_group)" --name "$name"
   done
   az functionapp stop --resource-group "$(terraform output -raw resource_group)" --name "$(terraform output -raw retention_name)"
   az functionapp start --resource-group "$(terraform output -raw resource_group)" --name "$(terraform output -raw retention_name)"
   ```

5. **Send the ratings to your own core.** Install the RateXp plugin as
   [Quick start](../README.md#quick-start-install-ratexp) tells. The plugin sends to the hosted
   core. To send to your own core, add this line to your shell profile, such as `~/.bashrc` or
   `~/.zshrc`. Then start the coding agent again:

   ```bash
   export RATEXP_URL=<the URL of your core>
   ```

   - **The URL of your core:** `terraform output -raw core_url` shows the URL.

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
- **Retention:**
  - **Count:** `retention.keep_newest` in `core/config.yaml` sets how many of the newest ratings
    stay.
  - **Switch:** `app_be_psql`, `custom_psql` and `phoenix` each have a `retention` switch in
    `core/config.yaml`.
  - **Deletion:** the `retention` Function deletes the older ratings and conversations
    permanently, one time each hour. The image of the `retention` Function contains the same
    `core/config.yaml`.
  - **Dynatrace and Bluebox:** core never deletes from Dynatrace or Bluebox.
- **Read source of the app:**
  - `read_adapters` in `app/ratexp/config.yaml` selects the one read source.
  - `dynatrace_query_url` and the Dynatrace token give only the credentials of the read source.
- **After a change:**
  - **In `terraform.tfvars`:** Run `terraform apply` again.
  - **In a `config.yaml`:** The image contains the `config.yaml` file. Build and push the image
    again (step 2). Then stop and start the web app (step 4).

### Dev environment: test a change before prod

You can run RateXp in two Azure environments: prod and dev. Each change goes to dev first.
After the check on dev, the same images go to prod.

- **Names:** Each Azure part of dev has `dev` in its name (`rg-ratexp-dev`, `ratexp-dev-core`,
  `https://ratexp-dev-app.azurewebsites.net`).
- **Shared with prod:** Dev uses the PostgreSQL server and the Language account of prod. On
  the PostgreSQL server of prod, dev has a database of its own.
- **Terraform:** Dev is the `dev` workspace of the Terraform stack in `infra/`. Prod is the
  `default` workspace.
- **`infra/dev.tfvars`:** Holds only the values that are different on dev. Git ignores
  `dev.tfvars`. Terraform also reads the `terraform.tfvars` of prod, and a value in
  `dev.tfvars` wins. Thus, keep `terraform.tfvars`. Set these values in `dev.tfvars`:
  - **`environment`:** `"dev"`.
  - **`phoenix_project_name`:** A Phoenix project of its own.
  - **`seed_schedule`:** A slow schedule, because each seeder run costs model credits.
  - **`shared_language_account_name` and `shared_language_resource_group`:** The Language
    account of prod. Azure gives one free F0 Language account to each subscription.
  - **`shared_postgres_server_name` and `shared_postgres_resource_group`:** The PostgreSQL
    server of prod.
  - **`pg_database`:** The name of the dev database on that server, for example
    `"ratexp_dev"`.
- **Dynatrace and Bluebox:** Dev core writes to the same Dynatrace tenant and Bluebox
  workspace as prod. For how the Dynatrace views keep the dev records apart, see
  [View options](./read-the-feedback.md#view-options-where-to-see-the-human-evals).

#### Create dev: from zero to live

1. **Create the dev workspace one time.** `terraform workspace new` also selects the new
   workspace. Thus, select `default` again. Run these commands in `infra/`:

   ```bash
   terraform workspace new dev
   terraform workspace select default
   ```

2. **Select dev for the shell.** Then each `terraform` command in the shell uses dev, and
   each `terraform output` gives a dev name:

   ```bash
   export TF_WORKSPACE=dev
   ```

3. **Create the Azure resources of dev.** Do not copy `terraform.tfvars.example`, because the
   copy replaces the values of prod. Run this command in `infra/`:

   ```bash
   terraform init && terraform apply -var-file=dev.tfvars
   ```

4. **Do steps 2, 3 and 4 of Deploy to Azure.** Use
   [Steps: deploy RateXp to Azure](#steps-deploy-ratexp-to-azure).
   Also build and push the seeder image, as
   [Optional extras](#optional-extras-set-in-terraformtfvars) tells.
   Do not do step 5, because step 5 sends your own ratings to dev.
   - **Step 3 on dev:** Run Part B connected to the dev database (`pg_database`). In Part B,
     also write the dev database in place of the database name `ratexp`.
5. **Publish the dev Dynatrace dashboard.** Run this command in `core/`:

   ```bash
   uv run python -m modules.dashboard.publish_to_dynatrace dev
   ```

6. **Install the dev copy of the RateXp Dynatrace app.** Run this command in
   `app/dynatrace/`:

   ```bash
   npm run deploy:dev
   ```

#### Deploy a change: dev first, then prod

1. **Select dev for the shell.** Run this command:

   ```bash
   export TF_WORKSPACE=dev
   ```

2. **Deploy each changed image to dev.** Do step 2 and step 4 of
   [Steps: deploy RateXp to Azure](#steps-deploy-ratexp-to-azure) for
   each changed image.
3. **Deploy a Dynatrace change to dev.** For a change to `dashboard_for_dynatrace.yaml`, do
   step 5 of "Create dev". For a change to `app/dynatrace/`, do step 6 of "Create dev".
4. **Check the change on dev.** Open the RateXp app of dev at
   <https://ratexp-dev-app.azurewebsites.net>. For a change to `core/ratexp-*.sh` or to the
   plugin files (`.claude-plugin/`, `.cursor-plugin/`), also run the agent test on dev. The **Dev**
   item of [Tests](../CONTRIBUTING.md#tests-per-component-and-whole-app) tells how.
5. **Copy the tested images to prod.** Name each changed image (`core`, `app`, `seeder`,
   `retention`). The copy script copies each image to the registry of prod, with no new
   build. Then the copy script stops and starts each prod web app or Function. For another
   `project`, change `PROJECT` at the top of the copy script. Run this command in the repo
   root:

   ```bash
   infra/copy-dev-images-to-prod.sh core app
   ```

6. **Publish a Dynatrace dashboard change to prod.** Run this command in `core/`:

   ```bash
   uv run python -m modules.dashboard.publish_to_dynatrace
   ```

7. **Deploy a RateXp Dynatrace app change to prod.** Run this command in `app/dynatrace/`:

   ```bash
   npm run deploy
   ```

8. **Apply a Terraform change to dev, then to prod.** On dev, always add `dev.tfvars`.
   Without `dev.tfvars`, Terraform replaces the dev resources with the names of prod. Run this
   command in `infra/`, with `TF_WORKSPACE=dev` exported:

   ```bash
   terraform apply -var-file=dev.tfvars
   ```

   Then apply the change to prod. `TF_WORKSPACE=default` selects prod, also when the shell
   exports dev:

   ```bash
   TF_WORKSPACE=default terraform apply
   ```

<!-- shared ../README.md destinations -->
### Destinations: where core writes the feedback

See [Destinations](../README.md#destinations-where-core-writes-the-feedback) in the README.
<!-- /shared -->
