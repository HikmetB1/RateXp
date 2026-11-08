# app

`app/` holds the apps that show the feedback that core stored. Each app is a separate project:

- [ratexp/](./ratexp/README.md): The RateXp web app on Azure. Anyone can open the RateXp web
  app.
- [dynatrace/](./dynatrace/README.md): The RateXp Dynatrace app: the same Dashboard view inside
  Dynatrace, for users who log in to the tenant.

The Dynatrace dashboard is not in `app/`: core publishes the Dynatrace dashboard. See
[View options](../docs/read-the-feedback.md#view-options-where-to-see-the-human-evals).
