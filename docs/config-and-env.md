# Config and env: where settings live

- [Settings](#settings-every-key-is-required)
- [Secrets](#secrets-kept-out-of-git)
- [Stack variables](#stack-variables-defaults-in-docker-composeyml)

Each service keeps its settings and its secrets in two files next to its code:

| Service  | Settings                                  | Secrets                            |
|----------|-------------------------------------------|------------------------------------|
| core     | [`core/config.yaml`](../core/config.yaml)     | `core/.env` ([example](../core/.env.example))     |
| app      | [`app/ratexp/config.yaml`](../app/ratexp/config.yaml)       | `app/ratexp/.env` ([example](../app/ratexp/.env.example))       |
| seeder   | [`seeder/config.yaml`](../seeder/config.yaml) | `seeder/.env` ([example](../seeder/.env.example)) |

## Settings: every key is required

- `config.yaml` contains the settings. It contains no secrets.
- Each key is necessary. If a key is missing, the service stops at startup with an error.
  This makes `config.yaml` the single source of truth.
- core also reads its surveys from [`core/evals/`](../core/evals/). Each eval is one file over
  a shared `base.yaml`. core checks these files at startup with the same strict rules.
- The README of each service tells what each key and environment variable does:
  [core](../core/README.md), [app](../app/ratexp/README.md), [seeder](../seeder/README.md).

## Secrets: kept out of git

- `.env` contains the secrets and the environment variables that change for each environment.
- Git ignores all three `.env` files.

## Stack variables: defaults in docker-compose.yml

Some environment variables connect the services: the ports, `DATABASE_URL` and
`RATEXP_PUBLIC_URL`. [`docker-compose.yml`](../docker-compose.yml) has defaults for them that
work. To change one, put it in a `.env` file at the repository root. Compose reads that file
automatically.
