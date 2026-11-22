# Human evals: available and custom

- [Available human evals](#available-human-evals-the-question-of-each-eval)
- [Custom human evals](#custom-human-evals-copy-the-base-file)

<!-- shared ../README.md available-human-evals -->
## Available human evals: the question of each eval

See [Available human evals](../README.md#available-human-evals-the-question-of-each-eval) in
the README.
<!-- /shared -->

## Custom human evals: copy the base file

The hosted RateXp offers only the
[available human evals](#available-human-evals-the-question-of-each-eval). For custom evals,
deploy your own copy of RateXp. See [Custom deploy](./custom-deploy.md). And follow these steps:

1. **Copy the base file:** Copy [`core/evals/base.yaml`](../core/evals/base.yaml) to
   `core/evals/<custom-eval-name>.yaml`. Rename the placeholder.
2. **Write the eval:** Write the question and the two answers. The comments in `base.yaml`
   give the rules.
3. **Deploy your own RateXp:** See
   [Custom deploy](./custom-deploy.md#deploy-to-azure-from-zero-to-live).
4. **Answer the eval:** Type this command, and answer the eval in the survey:

   ```bash
   /ratexp:rate
   ```

   See [How to give a rating](../README.md#how-to-give-a-rating-the-command-and-the-survey).

- **After a change to an eval:** Build and deploy core again (steps 2 and 4 of
  [Custom deploy](./custom-deploy.md#steps-deploy-ratexp-to-azure)). Each user gets the
  changed eval at the start of the next session, with no new install.
