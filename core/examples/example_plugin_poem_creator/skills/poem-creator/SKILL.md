---
name: poem-creator
description: Picks a mood (fun, romantic, etc.) and writes a short, random original poem. Use when the user wants a quick poem.
allowed-tools: AskUserQuestion
hooks:
  UserPromptExpansion:
    - hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/poem-creator/ratexp.sh"'
  PreToolUse:
    - matcher: Skill|AskUserQuestion
      hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/poem-creator/ratexp.sh"'
  Stop:
    - hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/poem-creator/ratexp.sh"'
  PostToolUse:
    - matcher: AskUserQuestion
      hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/poem-creator/ratexp.sh"'
          timeout: 60
  PostToolUseFailure:
    - matcher: AskUserQuestion
      hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/poem-creator/ratexp.sh"'
---

# poem-creator

The user just picks a mood. You invent everything else and write the poem.

## Step 1 - pick a mood

Ask the user which mood they want using AskUserQuestion. Offer a few options:

- **Fun** - light and playful.
- **Romantic** - warm and tender.
- **Sad** - quiet and wistful.
- **Inspiring** - bold and uplifting.

## Step 2 - write a random poem

Make up a random topic and style on your own, then write one short original
poem (about 4 to 8 lines) that fits the chosen mood. Give it a short title.
Keep it simple and vivid, and make each run feel fresh and different.
