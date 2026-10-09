"""The project landing page must send users to the complete current kit."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_landing_page_links_current_kit_and_setup_command():
    source = ROOT / "skill-kit/xiaoheihe-publisher/scripts/xhh_cli.py"
    definitions = ast.parse(source.read_text(encoding="utf-8"))
    version = next(ast.literal_eval(node.value) for node in definitions.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "KIT_VERSION"
                           for target in node.targets))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"releases/tag/skill-kit-v{version}" in readme
    assert "python KIT/scripts/xhh_setup.py --apk USER.apk --install-java --confirm" in readme
    assert "docs/skill-kit.md" in readme
