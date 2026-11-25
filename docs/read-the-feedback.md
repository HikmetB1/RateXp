# Read the feedback: where to view the human evals

- [Destinations](#destinations-where-core-writes-the-feedback)
- [View options](#view-options-where-to-see-the-human-evals)
- [Filters](#filters-narrow-the-panels)
- [Download trajectories](#download-trajectories-the-ratings-that-match-the-filters)
- [Query box](#query-box-one-language-per-read-source)
- [Download trajectories after a query](#download-trajectories-after-a-query-what-the-file-contains)

<!-- shared ../README.md destinations -->
## Destinations: where core writes the feedback

See [Destinations](../README.md#destinations-where-core-writes-the-feedback) in the README.
<!-- /shared -->

## View options: where to see the human evals

Each destination that is on gets the same human evals. The table shows what you can do in each
view option. To switch a destination on, see [Config and env](./config-and-env.md).

| Use case | RateXp app: Query & table | RateXp app: Dashboard | Dynatrace dashboard | RateXp Dynatrace app | Dynatrace logs | Phoenix | Bluebox |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| See the total ratings and the percent good |  | ✓ | ✓ | ✓ |  |  |  |
| See the good and bad ratings over time |  | ✓ | ✓ | ✓ |  |  |  |
| Find the weakest skill, agent or eval |  | ✓ | ✓ | ✓ |  |  |  |
| See the top complaints and the top praise, by feedback theme |  | ✓ | ✓ | ✓ |  |  |  |
| Filter by type, skill, agent, eval, label or time range. See [Filters](#filters-narrow-the-panels). |  | ✓ | ✓ | ✓ |  |  |  |
| Read the newest ratings and their comments | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| View the conversation of one rating | ✓ | ✓ |  | ✓ |  |  |  |
| Save the conversation of one rating as JSON | ✓ | ✓ |  |  |  |  |  |
| Save the conversations that match the filters. See [Download trajectories](#download-trajectories-the-ratings-that-match-the-filters). |  | ✓ |  | ✓ |  |  |  |
| Find ratings with a query. See [Query box](#query-box-one-language-per-read-source). | ✓ |  |  |  | ✓ |  |  |
| Save the ratings that a query finds. See [Download trajectories after a query](#download-trajectories-after-a-query-what-the-file-contains). | ✓ |  |  |  |  |  |  |
| Ask questions in plain English |  |  |  |  |  |  | ✓ |

The dashboards show the same panels and filters. For how the dashboards stay the same, see
[ADR 0001](./adr/0001-one-panel-list-for-every-dashboard.md).

- **Environments in Dynatrace:** One Dynatrace tenant can hold the records of prod and dev.
  The Dynatrace dashboard and the RateXp Dynatrace app show the records of one environment.
  - **Prod:** the Dynatrace dashboard "RateXp" (document id `ratexp`) and the RateXp Dynatrace
    app.
  - **Dev:** the Dynatrace dashboard "RateXp (dev)" (document id `ratexp-dev`) and the dev copy
    of the RateXp Dynatrace app. See
    [Deploy](../app/dynatrace/README.md#deploy-how-the-ratexp-dynatrace-app-gets-to-dynatrace).
  - **Mark:** core marks each record with its environment. See `OTEL_RESOURCE_ATTRIBUTES` in
    [core](../core/README.md#env-the-secrets-core-reads).
- **Colors:** Green is good, red is bad and blue is neutral, in each dashboard.
  - **Green and red:** The score, and each label value of a group with `when_good` and
    `when_bad`, for example the feedback theme. **Top praise** is green and **Top complaints**
    is red.
  - **Blue:** The neutral values: the type, the name, the agent, the model, the eval, the
    comment and the values of the other label groups. The RateXp Dynatrace app and the
    Dynatrace dashboard use the blue and the green and red of Dynatrace.
- **Labels columns:** The feedback table shows one column for each label group.
  - **RateXp app and RateXp Dynatrace app:** The label columns stand under one **Labels**
    heading. The side panel of a conversation shows each label on its own line.
  - **Dynatrace dashboard:** A dashboard table has no shared heading, so the name of each label
    column starts with `Labels:`, for example **Labels: Business case**.

## Filters: narrow the panels

- **Type:** Skill or session. A session rating has no skill. When you select session, the
  Dashboard view hides the skill filter. The Dashboard view also marks **Skills rated** and
  **Percent good by skill** "Does not apply".
- **Other filters:** When you select a type, the other filters show only the values of that
  type.
- **Labels:** One filter for each label group in `core/config.yaml` (business case, language,
  task type and feedback theme as shipped). A rating has its own labels. The labels of the
  stored conversation of the rating win over the labels of the rating. Thus, a label filter
  applies to each panel. See [Labels](../README.md#feature-labels).
- **Time range:** **24h**, **7d**, **30d** or **All**, with **30d** as the default. The time
  range applies to each panel and to **Download trajectories**.

## Download trajectories: the ratings that match the filters

- **Which ratings:** **Download trajectories** saves the ratings that match the filters, as
  JSON.
- **Conversation:** Each rating has a `conversation` field: the stored conversation of the
  rating, or `null`.
- **Labels:** Each rating has a `labels` field: the value of each label group, with the labels
  of the stored conversation over the labels of the rating.
- **Order:** The newest rating comes first, by the time that core stored the rating.
- **Limit:** **Download trajectories** saves at most `list_max_limit` ratings. If more ratings
  match, the download contains the newest ratings.

## Query box: one language per read source

Type a query into the query box to filter the ratings. The query uses the language of the read
source:

| Read source | Query box language  |
|-------------|---------------------|
| PostgreSQL  | SQL                 |
| Dynatrace   | DQL                 |
| Phoenix     | `key:value` filters. Put a value with spaces in quotes: `feedback_theme:"Completion is slow"` |
| Bluebox     | not supported       |

## Download trajectories after a query: what the file contains

The query box shows only the newest `list_view_limit` matches. To get more matches, use
**Download trajectories** in the Query & table view. Each rating has a `conversation` field:
the stored conversation of the rating, or `null`. The contents of the download depend on the
last query that you ran:

| Last query that you ran | What the download contains |
|---|---|
| *(none)* | The newest `list_view_limit` ratings. |
| `SELECT * FROM feedback WHERE skill_name = 'poem-creator'` | **All** ratings for the `poem-creator` skill, up to `list_max_limit` ratings. |
| `SELECT * FROM feedback WHERE agent = 'claude-code'` | **All** ratings from the `claude-code` agent (skill runs and whole sessions), up to `list_max_limit` ratings. |
| `SELECT * FROM feedback WHERE eval_name = 'human-satisfaction'` | **All** ratings that answered the `human-satisfaction` eval, up to `list_max_limit` ratings. |
| A query for several skills, several agents and several evals | The newest `list_view_limit` ratings. |

For `list_view_limit` and `list_max_limit`, see [Config and env](./config-and-env.md).
