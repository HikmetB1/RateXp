---
name: redaction-test
description: Collects a (fake) username, email and password, echoes them back, then wraps up with RateXp — used to verify Azure PII redaction masks the stored conversation transcript.
allowed-tools: Bash(curl:*), Bash(sh:*), AskUserQuestion
---

# redaction-test

A throwaway skill for checking that transcript **PII redaction** works. It puts
some personal-looking details into the conversation, then uploads the transcript
through RateXp so you can confirm they come back masked on the dashboard.

> ⚠️ Use **fake / dummy** values only. Never type a real password or real
> credentials — the conversation gets uploaded. Names and emails are reliably
> redacted; a freeform password string may *not* be (it isn't a standard PII
> category), which is itself useful to observe.

## Step 1 — collect details

Ask the user, in one short message, to reply with three made-up test values:

- a **username** (use a person-like name, e.g. `Maria Garcia`),
- an **email** (e.g. `maria.garcia@contoso.com`),
- a **password** (a dummy string, e.g. `Hunter2!demo`).

Wait for their reply, then **echo the three values back** in your own confirming
message (e.g. "Got it — username Maria Garcia, email maria.garcia@contoso.com,
password Hunter2!demo."). Echoing them puts the same details in both a user
message and an agent message, so the test covers redaction on both.

## Step 2 — wrap up with RateXp

Run the command below and follow the instructions it prints. When it asks
*"may we store this full conversation?"*, pick **Yes** so the transcript is
uploaded (and redacted) — that's the whole point of the test.

```bash
curl -sS "https://ratexp-core-4y6yju.azurewebsites.net/snippet?every=1"
```
