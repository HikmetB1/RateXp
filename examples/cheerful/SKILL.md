---
name: cheerful
description: Adds a brief upbeat reply, then collects an OPTIONAL good/bad rating + comment via RateXp.
allowed-tools: Bash(curl:*), Bash(sh:*), AskUserQuestion
---

# cheerful

Two steps. Do both in the same turn.

## Step 1 — upbeat reply

Output one short upbeat message, picked at random from this list:

- "Love the energy — let's keep going."
- "That was satisfying! Onwards."
- "Great progress. You're crushing it."
- "Beautiful. One thing at a time and it adds up."

## Step 2 — wrap up with RateXp

Run the command below and follow the instructions it prints.

```bash
curl -sS "http://localhost:8000/snippet?adapter=app"
```

