from __future__ import annotations

from diskdoctor.memory.collectors.processes import classify_process, parse_ps_output


def test_parse_ps_output_sorts_by_rss_and_classifies_known_apps() -> None:
    rows = parse_ps_output(
        """  101     1 1048576 /Applications/Firefox.app/Contents/MacOS/firefox
  102     1  524288 /Applications/Docker.app/Contents/MacOS/Docker
  103     1  262144 /usr/local/bin/ollama
  104     1  131072 /Applications/Slack.app/Contents/MacOS/Slack
  105     1   65536 /usr/bin/login
""",
        limit=3,
    )

    assert [r.pid for r in rows] == [101, 102, 103]
    assert [r.kind for r in rows] == ["browser", "docker", "llm"]
    assert rows[0].rss_bytes == 1048576 * 1024
    assert rows[0].name == "Firefox"


def test_parse_ps_output_ignores_malformed_and_zero_rss_rows() -> None:
    rows = parse_ps_output(
        """bad row
  101     1       0 /usr/bin/true
  102     1    1024 /usr/bin/login
"""
    )

    assert len(rows) == 1
    assert rows[0].pid == 102
    assert rows[0].kind == "other"


def test_classify_process_matches_browser_docker_and_llm_markers() -> None:
    assert (
        classify_process("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        == "browser"
    )
    assert classify_process("/Applications/Arc.app/Contents/MacOS/Arc") == "browser"
    assert classify_process("/Applications/Docker.app/Contents/MacOS/Docker") == "docker"
    assert classify_process("/Applications/LM Studio.app/Contents/MacOS/LM Studio") == "llm"
    assert classify_process("/usr/local/bin/ollama") == "llm"
    assert classify_process("/Applications/Slack.app/Contents/MacOS/Slack") == "electron"
    assert (
        classify_process("/Applications/Visual Studio Code.app/Contents/MacOS/Electron")
        == "electron"
    )
    assert (
        classify_process(
            "/System/Library/PrivateFrameworks/TextInputUIMacHelper.framework/"
            "Versions/A/XPCServices/CursorUIViewService.xpc/Contents/MacOS/CursorUIViewService"
        )
        == "other"
    )
    assert classify_process("/usr/bin/login") == "other"


def test_classify_process_uses_word_boundaries_not_substrings() -> None:
    # "arc" (Arc browser) must not match inside "search"/"monarch"/"hierarchy".
    assert classify_process("/System/Library/CoreServices/Spotlight search") == "other"
    assert classify_process("/usr/local/bin/monarch-sync") == "other"
    assert classify_process("/opt/app/hierarchy-daemon") == "other"
    # "code"/"code helper" must not match "xcodebuild"/"decode"/"encoder"/"barcode".
    assert (
        classify_process("/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild") == "app"
    )
    assert classify_process("/usr/bin/videodecode") == "other"
    assert classify_process("/usr/local/bin/audio-encoder") == "other"
    assert classify_process("/usr/local/bin/barcode-scanner") == "other"
    # "llama" must not match inside "parallamatic"/"llamacpp-embedded-in-word".
    assert classify_process("/usr/local/bin/parallamatic") == "other"
    # "signal helper" must not swallow an unrelated "signald" daemon.
    assert classify_process("/usr/sbin/signald") == "other"
    # "teams.app" must not match a generic "teamspeak" binary.
    assert classify_process("/usr/local/bin/teamspeak-server") == "other"


def test_classify_process_still_matches_genuine_apps() -> None:
    assert (
        classify_process("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        == "browser"
    )
    assert classify_process("/Applications/Arc.app/Contents/MacOS/Arc") == "browser"
    assert classify_process("/Applications/Safari.app/Contents/MacOS/Safari") == "browser"
    assert classify_process("/Applications/Docker.app/Contents/MacOS/Docker") == "docker"
    assert classify_process("com.docker.hyperkit --something") == "docker"
    assert classify_process("/usr/local/bin/ollama") == "llm"
    assert classify_process("/Applications/LM Studio.app/Contents/MacOS/LM Studio") == "llm"
    assert classify_process("/Applications/Slack.app/Contents/MacOS/Slack") == "electron"
    assert (
        classify_process("/Applications/Visual Studio Code.app/Contents/MacOS/Electron")
        == "electron"
    )
    assert (
        classify_process("/Applications/Cursor.app/Contents/MacOS/Cursor Helper (Renderer)")
        == "electron"
    )
    assert classify_process("/usr/bin/login") == "other"


def test_parse_ps_output_filters_by_memory_provider() -> None:
    rows = parse_ps_output(
        """  101     1 1048576 /Applications/Firefox.app/Contents/MacOS/firefox
  102     1  524288 /Applications/Slack.app/Contents/MacOS/Slack
  103     1  262144 /usr/local/bin/ollama
""",
        provider_ids={"electron-apps"},
    )

    assert [row.kind for row in rows] == ["electron"]
    assert rows[0].name == "Slack"
