---
name: ratexp
description: Rate this chat with RateXp, or your most recent run of a skill. Type /ratexp:rate, then a skill's name, an eval's name, or both.
disable-model-invocation: true
---

# RateXp survey

Run `bash "<folder>/../../ratexp-cursor.sh" ask '<request>'`, where <folder>
is the folder that holds this SKILL.md, and <request> is the user's /ratexp:rate
request exactly as they typed it, such as `/ratexp:rate <skill> <eval>`. Then follow
what it prints, word for word. Do nothing else, and do not summarise the session.
If the command cannot run, tell the user that RateXp needs this command to run, and
stop. Never ask the survey questions yourself.
