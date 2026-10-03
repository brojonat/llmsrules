#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["cookiecutter>=2.6"]
# ///
"""Sync a cookiecutter template from a project generated from it (and grown since).

    sync-template.py TEMPLATE PROJECT key=value ... [--exclude PATH ...]          # dry run
    sync-template.py TEMPLATE PROJECT key=value ... [--exclude PATH ...] --write

The key=value pairs are the cookiecutter variables that reproduce PROJECT
(derived ones follow from cookiecutter.json). Steps:

1. Render TEMPLATE with those values into a scratch directory.
2. Compare with PROJECT's files (git's view: tracked plus untracked, minus
   ignored). Every project file that's new or differs is turned back into
   template form: each variable's value becomes {{cookiecutter.<key>}}
   (longest value first, whole values only, so never inside a hash), and any other {{ / {% / {# is escaped with
   {% raw %}. Files matching _copy_without_render are copied as is.
3. With --write, write those into TEMPLATE, render again, and check the
   result equals PROJECT. Remaining differences are printed and the exit
   status is 1: fix them by hand (usually a value that also appears as plain
   text in some file), then rerun.

--keep TEXT protects a literal that contains a value (the template's own
name contains the slug). --exclude skips a project path (e.g. TODO.md, CHANGELOG.md: per-project
history, not template content). Files only in the template are listed, never
deleted. Symlinks are skipped: cookiecutter turns them into empty
directories, so create them in hooks/post_gen_project.py.

JSON summary on stdout; per-file lines and diffs on stderr.
"""

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cookiecutter.generate import generate_context
from cookiecutter.main import cookiecutter
from cookiecutter.prompt import prompt_for_config

JINJA = re.compile(r"(\{\{|\{%|\{#)")


def project_files(root: Path) -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return {f for f in out.split("\0") if f and (root / f).is_file() and not (root / f).is_symlink()}


def files_in(root: Path) -> set[str]:
    """A rendered project's files, minus .git (a post-generation hook may run `git init`)."""
    files = (p.relative_to(root) for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    return {str(f) for f in files if f.parts[0] != ".git"}


def render(template: Path, values: dict[str, str], into: Path) -> Path:
    return Path(cookiecutter(str(template), no_input=True, output_dir=str(into), extra_context=values))


def context_for(template: Path, values: dict[str, str]) -> dict[str, str]:
    ctx = generate_context(context_file=str(template / "cookiecutter.json"), extra_context=values)
    return {k: v for k, v in prompt_for_config(ctx, no_input=True).items() if isinstance(v, str)}


def to_template(text: str, context: dict[str, str], keep: list[str]) -> str:
    """Escape Jinja that isn't ours, then replace each variable's value with its placeholder.

    Strings in `keep` (e.g. the template's own name, which contains the slug) are left as they are.
    """
    text = JINJA.sub(lambda m: "{% raw %}" + m.group(1) + "{% endraw %}", text)
    for i, k in enumerate(keep):
        text = text.replace(k, f"\x01{i}\x01")
    for key, value in sorted(context.items(), key=lambda kv: -len(kv[1])):
        if len(value) >= 3 and not key.startswith("_"):
            # Whole values only: "8765" must not match inside a hash in a lockfile.
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", "\0" + key + "\0", text)
    text = re.sub(r"\0(\w+)\0", lambda m: "{{cookiecutter." + m.group(1) + "}}", text)
    return re.sub("\x01(\\d+)\x01", lambda m: keep[int(m.group(1))], text)


def template_path(rel: str, context: dict[str, str]) -> str:
    names = {context[k]: k for k in ("package_name", "project_slug") if k in context}
    return "/".join("{{cookiecutter." + names[part] + "}}" if part in names else part for part in rel.split("/"))


def excluded(path: str, exclude: set[str]) -> bool:
    return any(path == x or path.startswith(x.rstrip("/") + "/") for x in exclude)


def compare(rendered: Path, project: Path, exclude: set[str]) -> tuple[list[str], list[str], list[str]]:
    have = {f for f in files_in(rendered) if not excluded(f, exclude)}
    want = {f for f in project_files(project) if not excluded(f, exclude)}
    changed = sorted(f for f in want & have if (project / f).read_bytes() != (rendered / f).read_bytes())
    return changed, sorted(want - have), sorted(have - want)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("template", type=Path)
    p.add_argument("project", type=Path)
    p.add_argument("values", nargs="+", metavar="key=value")
    p.add_argument("--exclude", action="append", default=[], metavar="PATH", help="project file or directory to leave out")
    p.add_argument("--keep", action="append", default=[], metavar="TEXT", help="literal text never to turn into a variable")
    p.add_argument("--write", action="store_true", help="write the changes into the template, then verify")
    args = p.parse_args()
    values = dict(v.split("=", 1) for v in args.values)
    template, project, exclude = args.template.resolve(), args.project.resolve(), set(args.exclude)
    (slug_dir,) = [d for d in template.iterdir() if d.is_dir() and d.name.startswith("{{")]
    context = context_for(template, values)
    no_render = json.loads((template / "cookiecutter.json").read_text()).get("_copy_without_render", [])

    with tempfile.TemporaryDirectory() as tmp:
        changed, added, only_template = compare(render(template, values, Path(tmp)), project, exclude)
    for f in changed + added:
        print(f"{'M' if f in changed else 'A'} {f}", file=sys.stderr)
    for f in only_template:
        print(f"? {f} (only in the template; left alone)", file=sys.stderr)
    summary: dict = {"changed": changed, "added": added, "only_in_template": only_template}

    if args.write:
        for f in changed + added:
            tpath = template_path(f, context)
            dest = slug_dir / tpath
            dest.parent.mkdir(parents=True, exist_ok=True)
            if any(fnmatch.fnmatch(f"{slug_dir.name}/{tpath}", pat) for pat in no_render):
                shutil.copy2(project / f, dest)
            else:
                dest.write_text(to_template((project / f).read_text(), context, args.keep))
                shutil.copymode(project / f, dest)
        with tempfile.TemporaryDirectory() as tmp:
            rendered = render(template, values, Path(tmp))
            changed, added, _ = compare(rendered, project, exclude)
            for f in changed:
                diff = subprocess.run(["diff", "-u", str(rendered / f), str(project / f)], capture_output=True, text=True)
                print(diff.stdout, file=sys.stderr)
            summary["still_different"] = changed + added
    print(json.dumps(summary, indent=2))
    return 1 if summary.get("still_different") else 0


if __name__ == "__main__":
    sys.exit(main())
