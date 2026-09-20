---
name: my-skill
description: <one line - what your skill does and when to use it>
allowed-tools: AskUserQuestion
hooks:
  UserPromptExpansion:
    - hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/my-skill/ratexp-skill.sh"'
  PreToolUse:
    - matcher: Skill|AskUserQuestion
      hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/my-skill/ratexp-skill.sh"'
  Stop:
    - hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/my-skill/ratexp-skill.sh"'
  PostToolUse:
    - matcher: AskUserQuestion
      hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/my-skill/ratexp-skill.sh"'
          timeout: 60
  PostToolUseFailure:
    - matcher: AskUserQuestion
      hooks:
        - type: command
          command: 'bash "${CLAUDE_PLUGIN_ROOT}/skills/my-skill/ratexp-skill.sh"'
---

# my-skill

<!-- Replace this section with your skill's instructions. -->

Do whatever your skill does here.

<!-- To rename this skill, rename skills/my-skill/ and update name + hook paths.
Try the plugin with: claude --plugin-dir ./template/plugin
RATEXP_EVERY and RATEXP_URL override the script's defaults. -->
