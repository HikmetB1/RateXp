# Custom deploy: run your own RateXp

- [Deploy to Azure](#deploy-to-azure-from-zero-to-live)
  - [Before you start](#before-you-start-the-tools-you-need)
  - [Steps](#steps-deploy-in-four-steps)
  - [Optional extras](#optional-extras-set-in-terraformtfvars)

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

### Steps: deploy in four steps

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

3. **Give the `core` and `app` web apps access to the database.** Connect to the database as
   its Entra admin. Run [`infra/grant-db-access.sql`](../infra/grant-db-access.sql) one time.
   The script needs the app names and the identity IDs. `terraform output` shows them. It
   also shows the URLs of your services.

4. **Stop each web app. Then start it again.** This makes Azure pull the image that you
   pushed. Do not use `az webapp restart`. It continues to use the old cached image.

### Optional extras: set in terraform.tfvars

These values in `terraform.tfvars` are optional:

- `enable_redaction`: creates the Azure AI Language account. Set `redaction_provider` to
  `azure` to make core mask personal data in transcripts with this account.
- `enable_labeling`: deploys the model that core uses to label conversations.
- `enable_seeder`: deploys the demo seeder. Then build and push `seeder_image`, as in step 2.
- `phoenix_*`: these values give core the endpoint, the key and the project of the Arize
  Phoenix destination.
- `bluebox_*`: these values give core the endpoint and the token of the Bluebox workspace.
