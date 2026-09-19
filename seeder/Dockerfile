# seeder - the optional demo feedback seeder.
#
#   docker build -t ratexp-seeder .
#
# The Azure Functions base image is what the deployed timer needs; the same image
# also runs the local loop (docker-compose.yml's `seed` service overrides the
# entrypoint). Nothing here is per-environment: config.yaml and the env vars pick
# what actually runs.

FROM mcr.microsoft.com/azure-functions/python:4-python3.12

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true

# function_app.py declares the timer with a decorator instead of a function.json,
# and the host only finds those with worker indexing switched on.
ENV AzureWebJobsFeatureFlags=EnableWorkerIndexing

# Installed with pip from requirements.txt, not from uv.lock: the Functions host
# looks for packages in the base image's own Python, not in a project venv.
COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt

# The host only finds function_app.py and host.json at the script root above, so
# azure_function/ is flattened into it; everything else keeps the path it has in the
# repo, which is what api/ and modules/ import each other by.
COPY azure_function/ /home/site/wwwroot/
COPY load_config.py config.yaml /home/site/wwwroot/
COPY api/ /home/site/wwwroot/api/
COPY modules/ /home/site/wwwroot/modules/
# The pool a run picks from (see modules/agent/load_skill_pool.py).
COPY skills/ /home/site/wwwroot/skills/
