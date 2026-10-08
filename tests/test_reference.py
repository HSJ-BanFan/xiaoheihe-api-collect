import copy
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = module("generate_reference")
        cls.checker = module("check_repo")

    def test_unexpected_private_field_is_rejected(self):
        data = self.generator.load_data(ROOT)
        poisoned = copy.deepcopy(data)
        poisoned["interfaces"][0]["account_alias"] = "private-alias"
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.generator.validate_data(poisoned)

    def test_review_cannot_be_generic_callable(self):
        data = self.generator.load_data(ROOT)
        entry = next(x for x in data["interfaces"] if x["collection"] == "review_required")
        entry["generic_call_allowed"] = True
        with self.assertRaisesRegex(ValueError, "allowlist"):
            self.generator.validate_data(data)

    def test_missing_reference_page_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("[missing](docs/no-such-page.md)", encoding="utf-8")
            self.assertTrue(self.checker.check_links(root))

    def test_binary_payload_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unapproved.jar").write_bytes(b"PK\x00\x01")
            self.assertTrue(self.checker.scan_files(root))

    def test_absolute_dependency_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("C:" + "\\" + "private\\source.py", encoding="utf-8")
            self.assertTrue(self.checker.scan_files(root))

    def test_credential_assignment_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.json").write_text('{"pkey": "' + "A" * 32 + '"}', encoding="utf-8")
            self.assertTrue(self.checker.scan_files(root))

    def test_nested_private_alias_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.json").write_text('{"items": [{"account_alias": "private"}]}', encoding="utf-8")
            self.assertTrue(self.checker.scan_files(root))

    def test_generated_files_are_current(self):
        data = self.generator.load_data(ROOT)
        for relative, expected in self.generator.render(data).items():
            self.assertEqual((ROOT / relative).read_text(encoding="utf-8"), expected, relative)

    def test_dynamic_game_paths_are_expanded(self):
        paths = {x["path"] for x in self.generator.load_data(ROOT)["interfaces"]}
        for game in ("apex", "csgo", "destiny2", "dota2"):
            self.assertIn(f"/game/{game}/get_player_leaderboards", paths)

    def test_group_named_exceptions_are_exact(self):
        data = self.generator.load_data(ROOT)
        actual = {x["path"] for x in data["interfaces"] if x["collection"] == "group_routes" and x["named_commands"]}
        self.assertEqual(actual, {"/chat_group/my_list", "/chat_group/user/list", "/chatroom/v2/chat_group_msg/list"})

    def test_post_payload_includes_annotated_dictionary_fields(self):
        data = self.generator.load_data(ROOT)
        entry = next(x for x in data["interfaces"] if x["path"] == "/bbs/app/api/link/post")
        names = {x["name"] for x in entry["parameters"]}
        self.assertTrue({"title", "desc", "link_tag", "post_type", "draft", "text", "words_count"} <= names)

    def test_named_group_parameter_locations_are_code_observed(self):
        data = self.generator.load_data(ROOT)
        entry = next(x for x in data["interfaces"] if x["path"] == "/chat_group/user/list")
        self.assertEqual({x["name"] for x in entry["parameters"] if x["location"] == "query"}, {"chat_group_id", "offset", "limit"})


class AssetRuleTests(unittest.TestCase):
    """The repository must not ship an asset the rights review has not pinned."""

    @classmethod
    def setUpClass(cls):
        cls.checker = module("check_repo")

    def test_shipped_tree_passes_every_scan(self):
        self.assertEqual(self.checker.scan_files(ROOT), [])

    def test_unreviewed_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cover.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            self.assertTrue(any("unreviewed asset" in error for error in self.checker.scan_files(root)))

    def test_replaced_asset_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / "assets").mkdir(parents=True)
            (root / "docs" / "assets" / "cover-emoji.svg").write_text(
                "<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            original = self.checker.PINNED_ASSETS
            self.checker.PINNED_ASSETS = {"docs/assets/cover-emoji.svg": "0" * 64}
            try:
                errors = self.checker.scan_files(root)
            finally:
                self.checker.PINNED_ASSETS = original
            self.assertTrue(any("digest drift" in error for error in errors))

    def test_asset_that_loads_remote_content_is_detected(self):
        payload = ("<svg xmlns='http://www.w3.org/2000/svg'><image href='https://example.com/a.png'/></svg>"
                   ).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / "assets").mkdir(parents=True)
            (root / "docs" / "assets" / "cover-emoji.svg").write_bytes(payload)
            original = self.checker.PINNED_ASSETS
            self.checker.PINNED_ASSETS = {
                "docs/assets/cover-emoji.svg": hashlib.sha256(payload).hexdigest()}
            try:
                errors = self.checker.scan_files(root)
            finally:
                self.checker.PINNED_ASSETS = original
            self.assertTrue(any("loads external content" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
