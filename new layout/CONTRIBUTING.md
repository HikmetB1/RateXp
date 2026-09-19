# Contributing

## README rules

These are about the README inside a folder, not the project README at the root. Your
reader knows the project but has never opened this folder.

1. **Write only what the folder cannot show by itself.**
   `ls` lists the files, docstrings explain the functions, `--help` prints the flags.
   Write down what stays hidden: a rule that fails silently, a generated file, an order
   that must not change. Nothing hidden, no README.

2. **Say each fact once.**
   A fact is anything that can quietly go out of date: a path, a command, a flag, a
   default, a version. Keep it in the one file closest to what it describes, and link to
   it from everywhere else. Check the code before writing it down.

3. **Stay under fifteen lines.**
   This file gets read once, quickly. If it needs headings to find your way around, it
   is documentation and belongs where that subject already lives.

4. **Fix it in the same commit that breaks it, or delete it.**
   The trigger is "I changed something this README states". So name exact paths and
   commands: a rename you can grep for is the only warning you get. When the folder can
   speak for itself, delete the file.

5. **Describe how things are now, not what changed.**
   The reader never saw the old version, so nothing here has to correct it. No
   "previously", no old versus new. That story belongs in the commit message.

## Code rules

Code has two readers who read the same way: a person skimming fast, and an agent holding
a few hundred lines, never the whole project. One pass should be enough for both.

1. **Write the least code that does the job.**
   No layer without a caller, no option nobody passes, no abstraction for a second case
   that does not exist. Two callers are a pattern, one is a guess.

2. **Make the call readable without opening the function.**
   The name has to carry what it returns, what it changes, and what it costs. A long
   name beats a comment explaining a short one.

3. **Name a file for the action it performs, where it performs one.**
   `redact_trajectory.py` and `apply_migrations.py` say what the file does before you
   open it. `utils.py` and `helpers.py` say nothing. Where a file is a thing rather
   than an action, name it that thing: `record_schemas.py`.

4. **Keep each file understandable on its own.**
   Import explicitly and keep the flow on the page. No relying on import order or a side
   effect three folders away. If a second file is required reading, say so once at the top.

5. **Comments say why, not what.**
   The code already says what it does. Comment a choice that looks wrong but is not, a
   constraint from outside the file, an order that must not change.

6. **Delete dead code instead of keeping it.**
   Commented-out blocks, unused helpers, dead flags, shims for callers that are gone.
   Remove them in the commit that kills them. Git remembers, readers assume it matters.

7. **Leave nothing that only makes sense against the old design.**
   Rule 6 for a whole feature. You are done when no name, branch, or comment points at
   what used to be there: no `v2` or `new_` beside the thing it replaced, no old path
   kept alive.