# seeder

## Config

Everything tunable lives in [`config.yaml`](./config.yaml), which explains each key inline:

- `schema_version`: ATIF version stamped on every seeded trajectory (matches core's)
- `model` / `temperature` / `max_rounds`: which model runs a skill, how it samples, and
  how many turns it gets before it has to rate
- `core_url`: where the rating and the trajectory are posted
- `interval_seconds`: gap between runs for the local loop only - the deployed timer takes
  its cadence from the `SEED_SCHEDULE` app setting instead
- `critical_ratio` / `oversized_ratio`: share of runs that review harshly, and share
  bloated past core's size limit on purpose so core stores a meta-only stub
- `system_prompt` / `task_prompt` / `critical_prompt`: the agent's own instructions
