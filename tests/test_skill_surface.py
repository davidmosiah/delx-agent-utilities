from pathlib import Path
import json
import re

from delx_agent_utilities.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_skill_document_is_present_and_safe():
    skill = ROOT / "skill" / "SKILL.md"
    assert skill.is_file()
    text = skill.read_text(encoding="utf-8")
    assert "call" in text
    assert re.search(r"[A-Z0-9_]*ALLOW_MUTATIONS\s*=\s*true", text) is None


def test_cli_call_local_uuid_tool(capsys):
    code = main(["call", "util_uuid_generate", "--json", "{}"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "uuids" in payload
    assert len(payload["uuids"]) == 1
