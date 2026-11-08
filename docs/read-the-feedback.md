# Read the feedback: where to view the human evals

- [Destinations](#destinations-where-core-writes-the-feedback)
- [View options](#view-options-where-to-see-the-human-evals)
- [Filters](#filters-narrow-the-panels)
- [Download trajectories](#download-trajectories-the-ratings-that-match-the-filters)
- [Query box](#query-box-one-language-per-read-source)
- [Download JSON](#download-json-what-the-file-contains)

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
| Filter by type, skill, agent, eval, label or time range. See [Filters](#filters-narrow-the-panels). |  | ✓ | ✓ | ✓ |  |  |  |
| Read the newest ratings and their comments | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| View the conversation of one rating | ✓ | ✓ |  | ✓ |  |  |  |
| Save the conversation of one rating as JSON | ✓ | ✓ |  |  |  |  |  |
| Save the conversations that match the filters. See [Download trajectories](#download-trajectories-the-ratings-that-match-the-filters). |  | ✓ |  | ✓ |  |  |  |
| Find ratings with a query. See [Query box](#query-box-one-language-per-read-source). | ✓ |  |  |  | ✓ |  |  |
| Save the ratings that a query finds. See [Download JSON](#download-json-what-the-file-contains). | ✓ |  |  |  |  |  |  |
| Ask questions in plain English |  |  |  |  |  |  | ✓ |

The dashboards show the same panels and filters. For how the dashboards stay the same, see
[ADR 0001](./adr/0001-one-panel-list-for-every-dashboard.md).

## Filters: narrow the panels

- **Type:** Skill or session. A session rating has no skill. When you select session, the
  Dashboard view hides the skill filter. The Dashboard view also marks **Skills rated** and
  **Percent good by skill** "Does not apply".
- **Other filters:** When you select a type, the other filters show only the values of that
  type.
- **Labels:** Business case, language and task type. A rating has the labels of its stored
  conversation. Thus, a label filter applies to each panel. See
  [Labels](../README.md#feature-labels).
- **Time range:** **24h**, **7d**, **30d** or **All**, with **30d** as the default. The time
  range applies to each panel and to **Download trajectories**.

## Download trajectories: the ratings that match the filters

- **Which ratings:** **Download trajectories** saves the ratings that match the filters, as
  JSON.
- **Conversation:** Each rating has a `conversation` field: the stored conversation of the
  rating, or `null`.
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
| Phoenix     | `key:value` filters |
| Bluebox     | not supported       |

## Download JSON: what the file contains

The query box shows only the newest `list_view_limit` matches. To get more matches, use
**Download JSON**. The file has the same fields as **Download trajectories**. The contents of
the download depend on the last query that you ran:

| Last query that you ran | What the download contains |
|---|---|
| *(none)* | The newest `list_view_limit` ratings. |
| `SELECT * FROM feedback WHERE skill_name = 'poem-creator'` | **All** ratings for the `poem-creator` skill, up to `query_max_rows` ratings. |
| `SELECT * FROM feedback WHERE agent = 'claude-code'` | **All** ratings from the `claude-code` agent (skill runs and whole sessions), up to `query_max_rows` ratings. |
| `SELECT * FROM feedback WHERE eval_name = 'human-satisfaction'` | **All** ratings that answered the `human-satisfaction` eval, up to `query_max_rows` ratings. |
| A query for several skills, several agents and several evals | The newest `list_view_limit` ratings. |

For `list_view_limit`, `list_max_limit` and `query_max_rows`, see
[Config and env](./config-and-env.md).
