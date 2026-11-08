# Read the feedback: apps, adapters and dashboards

- [Destinations](#destinations-where-core-writes-the-feedback)
- [Where to find the human evals](#where-to-find-the-human-evals-submitted-by-the-user-per-destination)
- [The RateXp app](#the-ratexp-app-views-and-downloads)
  - [Filters](#filters-narrow-the-dashboard-view)
  - [Download trajectories](#download-trajectories-the-ratings-that-match-the-filters)
  - [Query box](#query-box-one-language-per-read-source)
  - [Download JSON](#download-json-what-the-file-contains)
- [Dashboards](#dashboards-one-panel-list-for-the-ratexp-app-and-dynatrace)

<!-- shared ../README.md destinations -->
## Destinations: where core writes the feedback

See [Destinations](../README.md#destinations-where-core-writes-the-feedback) in the README.
<!-- /shared -->

## Where to find the human evals submitted by the user: per destination

core writes the human evals to one or more destinations. This section tells which files select
the destinations, and where each destination shows the human evals.

- **Write side:** `core/config.yaml` sets where core writes: one or more adapters.
- **Read side:** `app/ratexp/config.yaml` sets where the RateXp app reads from: one read
  source only, for now.
- **Settings files:** For `core/config.yaml` and `app/ratexp/config.yaml`, see
  [Config and env](./config-and-env.md).

To see the human evals, open one of the destinations that are on:

- **The RateXp app:**
  - **Views:** The human evals are in the
    [two views of the RateXp app](#the-ratexp-app-views-and-downloads).
  - **Read source:** The [README of the RateXp app](../app/ratexp/README.md) tells which read
    source each view works with.
- **Dynatrace:**
  - **Logs:** core writes each human eval as one log record. To list the human evals, run the
    DQL query `fetch logs | filter ratexp.record_type == "feedback"`.
  - **Dynatrace dashboard:** A dashboard that core publishes to Dynatrace. See
    [Dashboards](#dashboards-one-panel-list-for-the-ratexp-app-and-dynatrace).
  - **RateXp Dynatrace app:** An app that you install on Dynatrace. See
    [Dashboards](#dashboards-one-panel-list-for-the-ratexp-app-and-dynatrace).
- **Arize Phoenix:**
  - **Spans:** The human evals are in the Phoenix spans (traces).
- **Bluebox:**
  - **Questions:** Ask Bluebox questions in plain English, for example with `bluebox ask` in
    the Bluebox CLI.
  - **No RateXp app:** As of now, the RateXp app cannot read from Bluebox.

## The RateXp app: views and downloads

The [RateXp app](https://ratexp-app.azurewebsites.net/) shows the human evals when the human
evals arrive.

- **Views:** The RateXp app has the **Dashboard** view and the **Query & table** view.
- **Evals:** Each rating answers one eval. For the list of evals, see
  [Available human evals](../README.md#available-human-evals-the-question-of-each-eval).
- **Downloads:** **Download trajectories** and **Download JSON** both save the ratings as
  JSON. Each rating has a `conversation` field: the stored conversation of the rating, or
  `null`.

Each use case below names the view, and the part of the view that supports the use case:

| Use case | View | Part of the view |
|---|---|---|
| See the total ratings and the percent good | Dashboard | The **Total ratings**, **Percent good**, **Ratings in the last 24h** and **Skills rated** panels. |
| See the good and bad ratings over time | Dashboard | The **Good vs bad per day** line chart. |
| Find the weakest skill, agent or eval | Dashboard | The **Percent good by skill**, **Percent good by agent** and **Percent good by eval** bar charts. Each bar chart lists all values, worst first, and scrolls inside its box. |
| Look at one type, skill, agent, eval, label or time range | Dashboard | The filters. See [Filters](#filters-narrow-the-dashboard-view). |
| Read the newest ratings and their comments | Dashboard | The **Feedback** table, with an **Eval** column and a **Labels** column: the newest `list_view_limit` ratings that match the filters. |
| Read the newest ratings and their comments | Query & table | The **Feedback** table, with an **Eval** column and a **Labels** column: the newest `list_view_limit` ratings. |
| Read the conversation of one rating | Dashboard and Query & table | The blue chip in the **Trajectory** column of the **Feedback** table. The blue chip opens the conversation in a slide-over timeline. |
| Save the conversation of one rating | Dashboard and Query & table | The orange chip in the **Trajectory** column. The orange chip saves the conversation of the rating as JSON. |
| Save the conversations that match the filters | Dashboard | **Download trajectories**. See [Download trajectories](#download-trajectories-the-ratings-that-match-the-filters). |
| Find ratings with a query | Query & table | The query box. See [Query box](#query-box-one-language-per-read-source). |
| Save the ratings that a query finds | Query & table | **Download JSON**. See [Download JSON](#download-json-what-the-file-contains). |
| See the same panels in Dynatrace | The Dynatrace dashboard and the RateXp Dynatrace app | See [Dashboards](#dashboards-one-panel-list-for-the-ratexp-app-and-dynatrace). |

### Filters: narrow the Dashboard view

- **Type:** Skill or session. A session rating has no skill. When you select session, the
  Dashboard view hides the skill filter. The Dashboard view also marks **Skills rated** and
  **Percent good by skill** "Does not apply".
- **Other filters:** When you select a type, the other filters show only the values of that
  type.
- **Labels:** Business case, language and task type. A rating has the labels of its stored
  conversation. Thus, a label filter applies to each panel. core selects the labels with a
  model, from the lists in `core/config.yaml` (see `labeling` in the
  [core README](../core/README.md#config-every-key-in-configyaml)).
- **Time range:** **24h**, **7d**, **30d** or **All**, with **30d** as the default. The time
  range applies to each panel and to **Download trajectories**.

### Download trajectories: the ratings that match the filters

- **Which ratings:** **Download trajectories** saves the ratings that match the filters.
- **Order:** The newest rating comes first, by the time that core stored the rating.
- **Limit:** **Download trajectories** saves at most `list_max_limit` ratings. If more ratings
  match, the download contains the newest ratings.

### Query box: one language per read source

Type a query into the query box to filter the ratings. The query uses the language of the
[read source](#where-to-find-the-human-evals-submitted-by-the-user-per-destination):

| Read source | Query box language  |
|-------------|---------------------|
| PostgreSQL  | SQL                 |
| Dynatrace   | DQL                 |
| Phoenix     | `key:value` filters |
| Bluebox     | not supported       |

### Download JSON: what the file contains

The query box shows only the newest `list_view_limit` matches. To get more matches, use
**Download JSON**. The contents of the download depend on the last query that you ran:

| Last query that you ran | What the download contains |
|---|---|
| *(none)* | The newest `list_view_limit` ratings. |
| `SELECT * FROM feedback WHERE skill_name = 'poem-creator'` | **All** ratings for the `poem-creator` skill, up to `query_max_rows` ratings. |
| `SELECT * FROM feedback WHERE agent = 'claude-code'` | **All** ratings from the `claude-code` agent (skill runs and whole sessions), up to `query_max_rows` ratings. |
| `SELECT * FROM feedback WHERE eval_name = 'human-satisfaction'` | **All** ratings that answered the `human-satisfaction` eval, up to `query_max_rows` ratings. |
| A query for several skills, several agents and several evals | The newest `list_view_limit` ratings. |

`list_view_limit`, `list_max_limit` and `query_max_rows` are settings in
[`app/ratexp/config.yaml`](../app/ratexp/config.yaml).

## Dashboards: one panel list for the RateXp app and Dynatrace

RateXp has three dashboards. One dashboard is in the RateXp app. Two dashboards are in
Dynatrace: the Dynatrace dashboard and the RateXp Dynatrace app.

- **Dashboard view of the RateXp app:** Opens in the RateXp app. The panels come from
  `dashboard_for_app.yaml`, with SQL queries. The Dashboard view comes with the RateXp app.
- **Dynatrace dashboard:** Opens in Dynatrace, as a dashboard. The panels come from
  `dashboard_for_dynatrace.yaml`, with DQL queries. To install the Dynatrace dashboard, run
  `publish_to_dynatrace.py`. The docstring of `publish_to_dynatrace.py` tells how.
- **RateXp Dynatrace app:** Opens in Dynatrace, as an app. The panels come from a copy of
  `dashboard_for_dynatrace.yaml`, with DQL queries. To install the RateXp Dynatrace app, run
  `npm run deploy` in [`app/dynatrace/`](../app/dynatrace/README.md).

The three dashboards are different in these points:

| Point | Dashboard view of the RateXp app | Dynatrace dashboard | RateXp Dynatrace app |
|---|---|---|---|
| Rows in the **Feedback** table | The newest `list_view_limit` ratings | The newest ratings, up to the fixed `limit 10` in `dashboard_for_dynatrace.yaml` | Same as the Dynatrace dashboard |
| **Download trajectories** | Yes | No | Yes (the `download` query, which ends in `limit 1000`) |
| **Trajectory** column, which opens the conversation of a rating | Yes | No | Yes |
| **Type** is session | Hides the Skill filter and marks **Skills rated** and **Percent good by skill** "Does not apply" | Skill shows only "(none)", and **Skills rated** shows "n/a: session" | Same as the Dashboard view of the RateXp app |

How the three dashboards stay the same:

- **Dashboard files:** All dashboard files are in
  [`core/modules/dashboard/`](../core/modules/dashboard/).
- **One shared base:** `dashboard_base.yaml` lists the panels that each dashboard must have.
  Each panel has an id, a title and a kind (number, line, bar or table). The file of each
  platform must contain all of the panels in `dashboard_base.yaml`. If a panel is missing,
  `core/tests/test_clone_dashboard_from_base.py` fails.
- **Same panels and filters:** The three dashboards share the panels, the order of the panels
  and the filters.
- **Panel copy:** The RateXp Dynatrace app keeps a copy of the panels of
  `dashboard_for_dynatrace.yaml`. The tests of the RateXp Dynatrace app make sure that the copy
  is the same as `dashboard_for_dynatrace.yaml`.
- **Data in Dynatrace:** The Dynatrace dashboard and the RateXp Dynatrace app read the logs that
  core writes to Dynatrace.
- **Access in Dynatrace:** Only the users of your tenant can open the Dynatrace dashboard and the
  RateXp Dynatrace app.
