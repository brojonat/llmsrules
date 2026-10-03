"""Finish a generated project: link its agent skill, and make it a git repository.

The skill lives in .agents/skills/ (where `npx skills` installs, for every
agent); Claude Code reads .claude/skills/. A symlink can't ship in the
template itself: cookiecutter turns it into an empty directory.

`git init` without a commit: the docs commit skills-lock.json, the dashboard
shows each model's git revision, and an approved model is committed and
tagged. What goes in the first commit is the user's call.
"""

import subprocess
from pathlib import Path

link = Path(".claude/skills/new-model")
link.parent.mkdir(parents=True, exist_ok=True)
if not link.is_symlink():
    link.symlink_to("../../.agents/skills/new-model")

if not Path(".git").exists():
    subprocess.run(["git", "init", "--quiet"], check=False)
