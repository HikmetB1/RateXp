# Read the feedback: apps, adapters and dashboards

- [Where to find the feedback](#where-to-find-the-feedback-per-destination)
- [The RateXp app](#the-ratexp-app-two-views)
  - [Dashboard view](#dashboard-view-panels-and-filters)
  - [Query & table view](#query--table-view-ratings-and-the-query-box)
  - [Query box](#query-box-one-language-per-read-source)
  - [Download JSON](#download-json-what-the-file-contains)
- [Dashboards](#dashboards-one-panel-list-drawn-in-the-app-and-dynatrace)

## Where to find the feedback: per destination

`core/config.yaml` sets where core writes: one or more adapters. `app/ratexp/config.yaml` sets
where the RateXp app reads from: one read source only, for now. For these files, see
[Config and env](./config-and-env.md). Each destination shows only the data that its own
adapter wrote:

- **The RateXp app:** in [its two views](#the-ratexp-app-two-views). The
  [README of the RateXp app](../app/ratexp/README.md) tells which read source each view works
  with.
- **Dynatrace:** in its logs, in its
  [dashboard](#dashboards-one-panel-list-drawn-in-the-app-and-dynatrace), or in the RateXp
  Dynatrace app.
- **Arize Phoenix:** in its spans (traces), or in its built-in dashboard. On the current
  Phoenix plan, that dashboard is fixed. You cannot make a custom one.
- **Bluebox:** ask it questions in plain English. The RateXp app cannot read from Bluebox.

## The RateXp app: two views

The [RateXp app](https://ratexp-app.azurewebsites.net/) shows the feedback when it arrives.
It has two views: **Dashboard** and **Query & table**. Each rating answers one eval. For the
list of evals, see [Available evals](../README.md#available-evals-what-each-one-asks).

Both downloads, **Download trajectories** and **Download JSON**, save JSON with at most 1000
ratings (`list_max_limit` in `app/ratexp/config.yaml`). Each rating has its stored conversation,
or `null` if core stored no conversation for it.

### Dashboard view: panels and filters

The **Dashboard** view has these panels:

- four numbers: **Total ratings**, **Percent good**, **Ratings in the last 24h** and
  **Skills rated**;
- **Good vs bad per day**, a line chart;
- **Percent good** per skill, per agent and per eval: bar charts that list every one, worst
  first, and scroll inside their box;
- **Feedback**: the newest 10 ratings, in the same table as Query & table.

The view has these filters: type, skill, agent, eval, the three labels and time range.

- **Type:** skill or session. A session rating has no skill. When you select session, the
  Dashboard view hides the skill filter. It also marks **Skills rated** and **Percent good by
  skill** "Does not apply".
- **Other filters:** when you select a type, the other filters show only the values of that
  type.
- **Labels:** a rating has the labels of its stored conversation. Thus, a label filter applies
  to every panel.

**Download trajectories** saves the ratings that match the filters, newest first. If more
ratings match than the limit, it saves the ones that core stored last.

The Dashboard view is also available as a Dynatrace app. See
[Dashboards](#dashboards-one-panel-list-drawn-in-the-app-and-dynatrace).

### Query & table view: ratings and the query box

- **Feedback** table: shows the latest ratings. Click a rating with a stored conversation to
  open that conversation in a slide-over timeline.
- **Eval** column: shows the eval that the rating answered.
- **Labels** column: shows the labels of the rating's conversation.
- **Query box:** type a query to filter the ratings.

### Query box: one language per read source

The query box in **Query & table** uses the language of the
[read source](#where-to-find-the-feedback-per-destination):

| Read source | Query box language  |
|-------------|---------------------|
| PostgreSQL  | SQL                 |
| Dynatrace   | DQL                 |
| Phoenix     | `key:value` filters |
| Bluebox     | not supported       |

### Download JSON: what the file contains

The query box shows only the most recent matches. To get more, use **Download JSON**. The
contents of the download depend on the last query that you ran:

| Last query run | What the download contains |
|---|---|
| *(none)* | The 10 most recent ratings. |
| `SELECT * FROM feedback WHERE skill_name = 'poem-creator'` | **Every** rating for that skill, up to 1000 ratings. |
| `SELECT * FROM feedback WHERE agent = 'claude-code'` | **Every** rating from that agent - skill runs and whole sessions - up to 1000 ratings. |
| `SELECT * FROM feedback WHERE eval_name = 'human-satisfaction'` | **Every** rating that answered that eval, up to 1000 ratings. |
| Anything spanning several skills, several agents and several evals | The 10 most recent ratings. |

## Dashboards: one panel list, drawn in the app and Dynatrace

All dashboard files are in [`core/modules/dashboard/`](../core/modules/dashboard/):

- **Dashboard in the RateXp app:** the **Dashboard** view. It uses the panels in
  `dashboard_for_app.yaml`, with SQL queries.
- **Dashboard in Dynatrace:** the same panels, from `dashboard_for_dynatrace.yaml`, with DQL
  queries. To send it to Dynatrace, run `publish_to_dynatrace.py`. Its docstring tells you how.
- **App in Dynatrace:** [`app/dynatrace/`](../app/dynatrace/README.md) shows the
  `dashboard_for_dynatrace.yaml` panels with the Dynatrace charts, from the logs that core
  writes to Dynatrace. Only the users of your tenant can open it. It also has the same filters
  as the RateXp app and **Download trajectories** (its `download` query). It keeps a copy of
  the panels. Its tests make sure that this copy is equal to the YAML.
- **One shared base:** `dashboard_base.yaml` lists the panels that every dashboard must have.
  Each panel has an id, a title and a kind (number, line, bar or table). The file of each
  platform must contain all of these panels. If one is missing,
  `core/tests/test_clone_dashboard_from_base.py` fails.
- **Same panels and filters:** all dashboards share panels, order and filters (now the RateXp
  app's Dashboard view, the Dynatrace dashboard and the Dynatrace app).

> **Where they differ:** when Type is session, the Dynatrace app works like the RateXp app (see
> [Dashboard view](#dashboard-view-panels-and-filters)). The Dynatrace dashboard cannot hide the
> Skill filter or mark a panel "Does not apply". There, Skill shows only "(none)" and Skills
> rated shows "n/a: session". The **Feedback** table of the Dynatrace dashboard also has no
> Trajectory column. In the RateXp app and the Dynatrace app, that column opens the
> conversation of a rating.
