from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from retail_ops_agent.deploy_wizard import (
    DEMO_LINE_PREFIX,
    Wizard,
    deploy_link,
    is_streamlit_app_url,
    parse_github_remote,
    with_demo_link,
)


def test_github_remotes_are_parsed_in_ssh_and_https_form() -> None:
    assert parse_github_remote("git@github.com:someone/retail-ops-agent.git") == (
        "someone",
        "retail-ops-agent",
    )
    assert parse_github_remote("https://github.com/someone/retail-ops-agent") == (
        "someone",
        "retail-ops-agent",
    )
    assert parse_github_remote("https://gitlab.com/someone/retail-ops-agent.git") is None


def test_the_deploy_link_fills_in_the_repository_branch_and_main_file() -> None:
    link = deploy_link("someone", "retail-ops-agent", "main")

    assert link.startswith("https://share.streamlit.io/deploy?")
    assert "repository=someone%2Fretail-ops-agent" in link
    assert "branch=main" in link
    assert "mainModule=dashboard%2Fapp.py" in link


def test_only_streamlit_app_urls_are_accepted() -> None:
    assert is_streamlit_app_url("https://cobalt-home-ops.streamlit.app")
    assert is_streamlit_app_url("https://cobalt-home-ops.streamlit.app/")
    assert not is_streamlit_app_url("http://cobalt-home-ops.streamlit.app")
    assert not is_streamlit_app_url("https://example.com")


def test_the_demo_link_goes_under_the_first_heading_and_is_replaced_not_repeated() -> None:
    readme = "# retail-ops-agent\n\nA prototype.\n"

    once = with_demo_link(readme, "https://a.streamlit.app")
    twice = with_demo_link(once, "https://b.streamlit.app")

    assert once.splitlines()[:3] == ["# retail-ops-agent", "", f"{DEMO_LINE_PREFIX} https://a.streamlit.app/"]
    assert twice.count(DEMO_LINE_PREFIX) == 1
    assert "https://b.streamlit.app/" in twice and "A prototype." in twice


class _Script:
    """Answers the wizard's questions in order and fakes the commands it runs."""

    def __init__(self, answers: list[str], outputs: dict[tuple[str, ...], str]) -> None:
        self.answers = answers
        self.outputs = outputs
        self.ran: list[tuple[str, ...]] = []
        self.opened: list[str] = []
        self.said: list[str] = []

    def ask(self, _question: str) -> str:
        return self.answers.pop(0)

    def run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        key = tuple(command)
        self.ran.append(key)
        known = key in self.outputs
        return subprocess.CompletedProcess(key, 0 if known else 1, self.outputs.get(key, ""), "")

    def open_url(self, url: str) -> None:
        self.opened.append(url)


def test_the_wizard_walks_through_to_the_readme_without_changing_github_unasked(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# retail-ops-agent\n")
    script = _Script(
        answers=[
            "",  # skip making the repository public
            "n",  # do not run the smoke test
            "",  # open the deploy page
            "",  # the app has built
            "https://cobalt-home-ops.streamlit.app",
            "",  # add it to the README
        ],
        outputs={
            ("git", "rev-parse", "--abbrev-ref", "HEAD"): "main",
            ("git", "remote", "get-url", "origin"): "git@github.com:someone/retail-ops-agent.git",
            ("git", "status", "--porcelain"): "",
            ("git", "rev-parse", "@{u}"): "abc",
            ("git", "rev-parse", "HEAD"): "abc",
            ("gh", "repo", "view", "someone/retail-ops-agent", "--json", "visibility", "-q", ".visibility"): (
                "PRIVATE"
            ),
        },
    )
    wizard = Wizard(
        ask=script.ask,
        say=script.said.append,
        run=script.run,
        open_url=script.open_url,
        has_command=lambda _name: True,
        readme=readme,
        env_file=tmp_path / ".env.local",
    )

    assert wizard.start() == 0

    assert script.opened == [deploy_link("someone", "retail-ops-agent", "main")]
    assert f"{DEMO_LINE_PREFIX} https://cobalt-home-ops.streamlit.app/" in readme.read_text()
    assert not [c for c in script.ran if c[:3] == ("gh", "repo", "edit") or c[:2] == ("git", "push")]
    assert any("Make the repository public" in note for note in wizard.notes)


def test_the_wizard_stops_without_a_github_remote() -> None:
    script = _Script(answers=[], outputs={("git", "rev-parse", "--abbrev-ref", "HEAD"): "main"})
    wizard = Wizard(ask=script.ask, say=script.said.append, run=script.run, open_url=script.open_url)

    assert wizard.start() == 1
    assert script.opened == []
