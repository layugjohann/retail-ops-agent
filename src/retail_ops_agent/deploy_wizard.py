"""An interactive wizard that walks you through deploying the dashboard to Streamlit Community Cloud.

    make deploy

It checks the repository is ready (committed, pushed, public on GitHub), offers to re-record Replay
Mode with a free-tier key, opens Streamlit Community Cloud's deploy page with the settings filled
in, and adds the public URL to the README. It asks before anything that changes the repository or
GitHub. Replay Mode needs no secrets, so none are asked for or stored.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from retail_ops_agent.replay import load_recordings

MAIN_MODULE = "dashboard/app.py"
PYTHON_VERSION = "3.13"
DEPLOY_PAGE = "https://share.streamlit.io/deploy"
README = Path("README.md")
ENV_FILE = Path(".env.local")
DEMO_LINE_PREFIX = "**Live demo (Replay Mode):**"

_GITHUB_REMOTE = re.compile(
    r"^(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([^/]+)/(.+?)(?:\.git)?/?$"
)
_STREAMLIT_APP_URL = re.compile(r"^https://[a-z0-9][a-z0-9-]*\.streamlit\.app/?$")


def parse_github_remote(url: str) -> tuple[str, str] | None:
    """The owner and repository of a GitHub remote URL, or None if it is not on GitHub."""
    match = _GITHUB_REMOTE.match(url.strip())
    return (match.group(1), match.group(2)) if match else None


def deploy_link(owner: str, repository: str, branch: str) -> str:
    """Streamlit Community Cloud's deploy page with the repository, branch and main file filled in."""
    query = urlencode({"repository": f"{owner}/{repository}", "branch": branch, "mainModule": MAIN_MODULE})
    return f"{DEPLOY_PAGE}?{query}"


def is_streamlit_app_url(url: str) -> bool:
    return bool(_STREAMLIT_APP_URL.match(url.strip()))


def with_demo_link(readme: str, url: str) -> str:
    """The README with a line linking the public demo: replaced if there is one, else added under the
    first heading."""
    line = f"{DEMO_LINE_PREFIX} {url.strip().rstrip('/')}/"
    lines = readme.splitlines()
    for i, existing in enumerate(lines):
        if existing.startswith(DEMO_LINE_PREFIX):
            lines[i] = line
            return "\n".join(lines) + "\n"
    heading = next((i for i, existing in enumerate(lines) if existing.startswith("# ")), None)
    if heading is None:
        return "\n".join([line, "", *lines]) + "\n"
    return "\n".join([*lines[: heading + 1], "", line, *lines[heading + 1 :]]) + "\n"


type Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), capture_output=True, text=True, check=False)


@dataclass
class Wizard:
    """The wizard's steps, with its input, output and commands passed in so it can be tested."""

    ask: Callable[[str], str] = input
    say: Callable[[str], None] = print
    run: Run = _run
    open_url: Callable[[str], object] = webbrowser.open
    has_command: Callable[[str], bool] = lambda name: shutil.which(name) is not None
    readme: Path = README
    env_file: Path = ENV_FILE
    notes: list[str] = field(default_factory=list[str])

    def confirm(self, question: str, *, default: bool = False) -> bool:
        hint = "[Y/n]" if default else "[y/N]"
        answer = self.ask(f"{question} {hint} ").strip().lower()
        return default if not answer else answer in ("y", "yes")

    def output(self, *command: str) -> str | None:
        done = self.run(command)
        return done.stdout.strip() if done.returncode == 0 else None

    def heading(self, text: str) -> None:
        self.say(f"\n== {text} ==")

    def start(self) -> int:
        self.say(
            "This wizard walks you through deploying the Cobalt Home dashboard to Streamlit Community "
            "Cloud. The public demo opens in Replay Mode, which needs no model key and no secrets."
        )
        github = self.check_repository()
        if github is None:
            return 1
        owner, repository, branch = github
        self.check_visibility(owner, repository)
        self.check_recordings()
        self.check_smoke_test()
        self.deploy(owner, repository, branch)
        self.record_url()
        self.heading("Done")
        for note in self.notes:
            self.say(f"- {note}")
        self.say("Mark ticket 19 done once the public URL opens in Replay Mode.")
        return 0

    def check_repository(self) -> tuple[str, str, str] | None:
        self.heading("1. The repository")
        branch = self.output("git", "rev-parse", "--abbrev-ref", "HEAD")
        if branch is None:
            self.say("This is not a git repository. Run the wizard from the project's root.")
            return None
        remote = self.output("git", "remote", "get-url", "origin")
        github = parse_github_remote(remote) if remote else None
        if github is None:
            self.say(
                "There is no GitHub remote called origin. Streamlit Community Cloud deploys from GitHub: "
                "create a repository there, `git remote add origin <url>`, push, and run the wizard again."
            )
            return None
        owner, repository = github
        self.say(f"GitHub repository {owner}/{repository}, branch {branch}.")
        if self.output("git", "status", "--porcelain"):
            self.say("You have uncommitted changes. Streamlit deploys what is pushed, not your working tree.")
            if not self.confirm("Carry on anyway?"):
                return None
        if branch != "main":
            self.say(
                f"You are on {branch}, not main. Streamlit redeploys whenever the deployed branch "
                "changes, so main is usual."
            )
            if not self.confirm(f"Deploy {branch} anyway?"):
                return None
        upstream = self.output("git", "rev-parse", "@{u}")
        if upstream is None or upstream != self.output("git", "rev-parse", "HEAD"):
            self.say(f"{branch} has commits GitHub does not have yet (or no upstream).")
            if self.confirm(f"Push {branch} to origin now?"):
                pushed = self.run(["git", "push", "-u", "origin", branch])
                self.say("Pushed." if pushed.returncode == 0 else f"Push failed:\n{pushed.stderr}")
            else:
                self.notes.append(f"Push {branch} before deploying; Streamlit only sees what is on GitHub.")
        return owner, repository, branch

    def check_visibility(self, owner: str, repository: str) -> None:
        self.heading("2. Repository visibility")
        if not self.has_command("gh"):
            self.say(
                "The GitHub CLI (gh) is not installed, so the wizard cannot check whether the repository "
                "is public. A public demo of a portfolio project is easiest from a public repository: "
                "check Settings > General > Danger Zone on GitHub."
            )
            return
        visibility = self.output(
            "gh", "repo", "view", f"{owner}/{repository}", "--json", "visibility", "-q", ".visibility"
        )
        if visibility is None:
            self.say("gh could not read the repository. Run `gh auth login` and check it by hand.")
            return
        self.say(f"The repository is {visibility.lower()}.")
        if visibility.upper() == "PUBLIC":
            return
        self.say(
            "Make it public before deploying so a hiring manager can read the code behind the demo. "
            "Check first that nothing secret was ever committed: .env.local is ignored by git."
        )
        answer = self.ask(f"Type 'public' to make {owner}/{repository} public now, or press Enter to skip: ")
        if answer.strip().lower() != "public":
            self.notes.append("Make the repository public on GitHub, or grant Streamlit access to it.")
            return
        made = self.run(
            [
                "gh",
                "repo",
                "edit",
                f"{owner}/{repository}",
                "--visibility",
                "public",
                "--accept-visibility-change-consequences",
            ]
        )
        self.say("It is public now." if made.returncode == 0 else f"gh refused:\n{made.stderr}")

    def check_recordings(self) -> None:
        self.heading("3. Replay Mode's recordings")
        recordings = load_recordings()
        if not recordings:
            self.say("There are no recordings. Run `make record` and commit them before deploying.")
            self.notes.append("Record Ops Days with `make record` and commit them.")
            return
        for recording in recordings:
            self.say(f"- {recording.title} (recorded with {recording.model})")
        if not any(r.model.startswith("offline") for r in recordings):
            return
        self.say(
            "Some recordings were made with the offline scripted model, so their Investigations say they "
            "were not investigated. With a free-tier Groq or Gemini key in .env.local, `make record` "
            "records them again with a real model (it is paced for the free tier and costs nothing)."
        )
        if not self.env_file.exists():
            self.say("There is no .env.local yet: copy .env.example and add a free-tier key to do that.")
            self.notes.append("Re-record with a free-tier key (`make record`), commit and push.")
            return
        if self.confirm("Record them again now?"):
            recorded = self.run(["make", "record"])
            if recorded.returncode == 0:
                self.say("Recorded. Commit and push the recordings so the deployed demo plays them.")
                self.notes.append("Commit and push the new recordings in src/retail_ops_agent/recordings/.")
            else:
                self.say(f"Recording failed:\n{recorded.stderr[-2000:]}")

    def check_smoke_test(self) -> None:
        self.heading("4. Smoke test")
        if not self.confirm("Run the Replay Mode smoke test before deploying?", default=True):
            return
        tested = self.run(["uv", "run", "pytest", "tests/test_replay.py", "-q"])
        tail = tested.stdout.strip().splitlines()[-1:] or ["(no output)"]
        self.say(("Passed: " if tested.returncode == 0 else "FAILED: ") + tail[0])
        if tested.returncode != 0:
            self.notes.append("Fix the failing Replay Mode smoke test before sharing the link.")

    def deploy(self, owner: str, repository: str, branch: str) -> None:
        self.heading("5. Deploy on Streamlit Community Cloud")
        link = deploy_link(owner, repository, branch)
        self.say(
            "Sign in at https://share.streamlit.io with GitHub (authorise it to see the repository), "
            "then create an app with these settings:\n"
            f"  Repository:      {owner}/{repository}\n"
            f"  Branch:          {branch}\n"
            f"  Main file path:  {MAIN_MODULE}\n"
            f"  App URL:         pick something short, such as cobalt-home-ops\n"
            f"  Advanced > Python version: {PYTHON_VERSION}\n"
            "  Advanced > Secrets: leave empty. Replay Mode needs no key; never paste a key you would "
            "mind a Visitor spending.\n"
            "Dependencies are read from uv.lock and pyproject.toml in the repository."
        )
        self.say(f"Deploy page with the settings filled in:\n  {link}")
        if self.confirm("Open it in your browser?", default=True):
            self.open_url(link)
        self.ask("Press Enter once the app has finished building and opens in Replay Mode... ")

    def record_url(self) -> None:
        self.heading("6. The public URL")
        while True:
            url = self.ask("Paste the app's URL (https://<name>.streamlit.app), or press Enter to skip: ")
            if not url.strip():
                self.notes.append("Add the public URL to the README.")
                return
            if is_streamlit_app_url(url):
                break
            self.say("That does not look like https://<name>.streamlit.app.")
        if not self.readme.exists():
            self.notes.append(f"Add {url.strip()} to the README.")
            return
        if self.confirm(f"Add {url.strip()} to {self.readme}?", default=True):
            self.readme.write_text(with_demo_link(self.readme.read_text(), url))
            self.say(f"Updated {self.readme}.")
            self.notes.append(f"Commit and push {self.readme}.")


def main() -> int:
    try:
        return Wizard().start()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Nothing else was changed.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
