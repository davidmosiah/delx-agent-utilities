"""Verify resources in the installed distribution, not the source tree."""
from importlib.metadata import distribution
from pathlib import Path

root = Path(__file__).resolve().parents[1]
dist = distribution("delx-agent-utilities")
for source, resource in (("skill/SKILL.md", "delx_agent_utilities/skill/SKILL.md"), ("MIGRATION.md", "delx_agent_utilities/MIGRATION.md"), ("NETWORK_SECURITY.md", "delx_agent_utilities/NETWORK_SECURITY.md")):
    files = {str(path): path for path in dist.files or []}
    assert resource in files, f"missing installed resource: {resource}"
    assert dist.locate_file(files[resource]).read_bytes() == (root / source).read_bytes(), resource
print("installed wheel resources match source")
