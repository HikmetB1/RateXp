---
name: <your-skill-name>
description: <one line - what your skill does and when to use it>
allowed-tools: AskUserQuestion
hooks:
  UserPromptExpansion:
    - hooks:
        - type: command
          command: 'bash "${CLAUDE_PROJECT_DIR}/.claude/skills/<your-skill-name>/ratexp-skill.sh"'
  PreToolUse:
    - matcher: Skill|AskUserQuestion
      hooks:
        - type: command
          command: 'bash "${CLAUDE_PROJECT_DIR}/.claude/skills/<your-skill-name>/ratexp-skill.sh"'
  Stop:
    - hooks:
        - type: command
          command: 'bash "${CLAUDE_PROJECT_DIR}/.claude/skills/<your-skill-name>/ratexp-skill.sh"'
  PostToolUse:
    - matcher: AskUserQuestion
      hooks:
        - type: command
          command: 'bash "${CLAUDE_PROJECT_DIR}/.claude/skills/<your-skill-name>/ratexp-skill.sh"'
          timeout: 60
  PostToolUseFailure:
    - matcher: AskUserQuestion
      hooks:
        - type: command
          command: 'bash "${CLAUDE_PROJECT_DIR}/.claude/skills/<your-skill-name>/ratexp-skill.sh"'
---

# <your-skill-name>

<!-- Replace this section with your skill's instructions. -->

Do whatever your skill does here.

<!-- Install SKILL.md and ratexp-skill.sh in .claude/skills/<your-skill-name>/.
Replace every <your-skill-name> above with the folder name.
RATEXP_EVERY and RATEXP_URL override the script's defaults. -->
