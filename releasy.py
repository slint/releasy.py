#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "click",
#     "survey",
#     "gitpython",
#     "packaging",
# ]
# ///

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal

import click
import survey
from git import GitCommandError, Repo
from packaging.version import Version


def run_shell_command(command):
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Command failed: {command}\n{result.stderr}")
    return result.stdout.strip()


def _sub_in_file(file, pattern, replacement) -> bool:
    with open(file, "r") as f:
        old_content = f.read()
    with open(file, "w") as f:
        new_content = re.sub(pattern, replacement, old_content)
        f.write(new_content)
    return new_content != old_content


VersionLevels = Literal["major", "minor", "patch", "pre", "dev", "post"]


def _bump_ver(ver: Version, level: VersionLevels) -> Version:
    version_tuple = ver._version
    release = version_tuple.release
    dev = version_tuple.dev
    pre = version_tuple.pre
    post = version_tuple.post

    if level in ("major", "minor", "patch"):
        release = version_tuple.release
        if level == "major":
            release = (release[0] + 1, 0, 0)
        if level == "minor":
            release = (release[0], release[1] + 1, 0)
        if level == "patch":
            release = (release[0], release[1], release[2] + 1)
        dev, pre, post = None, None, None

    if level == "pre" and pre is not None:
        pre = (pre[0], pre[1] + 1)
    if level == "dev" and dev is not None:
        dev = (dev[0], dev[1] + 1)
    if level == "post" and post is not None:
        post = (post[0], post[1] + 1)

    # Since we're using internal classes/attributes, we need to do a little dance to
    # make sure we generate a valid Version object to return
    new_ver_tuple = version_tuple._replace(release=release, dev=dev, pre=pre, post=post)
    new_ver = Version(str(ver))  #
    new_ver._version = new_ver_tuple
    return Version(str(new_ver))


def prompt_bump_version(ver: Version) -> Version:
    # TODO: We could smart here and even sort the bump options based on:
    #   - the previous bump
    #   - commit history (and conventional commits possibly?)

    # Determine what bump options we can have
    options = {level: _bump_ver(ver, level) for level in ("major", "minor", "patch")}
    if ver.is_prerelease:
        options["pre"] = _bump_ver(ver, "pre")
    if ver.is_devrelease:
        options["dev"] = _bump_ver(ver, "dev")
    if ver.is_postrelease:
        options["post"] = _bump_ver(ver, "post")

    option_idx = survey.routines.select(
        f"Options to bump version {ver}: ",
        options=[f"{bumped_ver} ({level})" for level, bumped_ver in options.items()],
    )
    assert option_idx is not None, "No option returned"

    # Somewhat hacky way to get the key from the options dict
    return options[list(options.keys())[option_idx]]


def rewrite_package_version(repo: Repo, new_version: Version) -> set[str]:
    matched_files = repo.git.grep(
        "--no-color", "--name-only", "-E", "__version__ = "
    ).splitlines()
    if len(matched_files) != 1:
        raise RuntimeError("Multiple files matched the version pattern")
    (version_file,) = matched_files

    _sub_in_file(
        version_file, r'__version__ = "(.+)"', rf'__version__ = "{str(new_version)}"'
    )
    return {version_file}


def update_changelog(repo: Repo, old_tag: str, new_tag: Version) -> set[str]:
    today = datetime.now()
    try:
        commits = repo.git.log(f"{old_tag}..HEAD", pretty="format:- %s%w(0,0,4)%+b")
    except GitCommandError as ex:
        click.secho("Failed to get commits", fg="yellow", err=True)
        click.secho(str(ex), fg="yellow", err=True)
        commits = ""

    changelog = f"Version v{new_tag} (released {today:%Y-%m-%d})\n\n{commits}"

    # Inject the new changelog right after the header
    changelog_file = Path("CHANGES.rst")
    _sub_in_file(
        changelog_file,
        r"(Changes\n=======\n)",
        rf"\1\n{changelog}\n",
    )
    return {changelog_file}


def rewrite_headers(repo: Repo, since_tag: Version, org: str) -> set[str]:
    current_year = datetime.now().year

    # Given the current year is 2024 and org is "CERN", replace...
    year_range_regex = re.compile(
        # ..."2019-2023 CERN" with "2019-2024 CERN"
        rf"Copyright \(C\) (\d{{4}})-(?!{current_year})(\d{{4}}) {org}"
    )
    year_single_regex = re.compile(
        # ..."2022 CERN" with "2022-2024 CERN"
        rf"Copyright \(C\) (?!{current_year})(\d{{4}}) {org}"
    )
    year_range_sub = rf"Copyright (C) \1-{current_year} {org}"

    changed_files = set()

    try:
        for fname in repo.git.diff("--name-only", f"{since_tag}").splitlines():
            if not Path(fname).exists():
                continue
            if _sub_in_file(fname, year_range_regex, year_range_sub):
                changed_files.add(fname)
            if _sub_in_file(fname, year_single_regex, year_range_sub):
                changed_files.add(fname)

            # TODO: Fix wrong package name in headers. E.g.:
            # "Invenio-RDM-Records is free software" -> "Invenio is free software"
    except GitCommandError:
        pass
    return changed_files


@click.command()
@click.argument("new_tag", required=False, default=None)
@click.option("--org", default="CERN")
def main(new_tag, org):
    """Generate a module release."""
    repo = Repo(".")
    old_tag = repo.git.describe("--tags", "--abbrev=0")
    old_ver = Version(old_tag)

    if new_tag is None:
        new_ver = prompt_bump_version(old_ver)
        new_tag = f"v{new_ver}"
    else:
        new_ver = Version(new_tag)

    changed_files = set()
    # Make all changes to file in a temporary directory
    # TODO: Maybe we can actually "unify" the interface for these functions. It's
    #       very important to make sure we pass and use correctly the "verbatim" git
    #       tag or the Version Python object, depending on the use-case.
    changed_files |= rewrite_package_version(repo, new_ver)
    changed_files |= rewrite_headers(repo, old_tag, org=org)
    changed_files |= update_changelog(repo, old_tag, new_ver)

    # Open the changelog for editing
    os.system("$EDITOR CHANGES.rst")

    repo.index.add(list(changed_files))
    repo.index.commit(f"📦 release: {new_tag}")
    repo.create_tag(new_tag, message=f"📦 release: {new_tag}")

    click.secho(f"Created {new_tag}", fg="green")


if __name__ == "__main__":
    main()
