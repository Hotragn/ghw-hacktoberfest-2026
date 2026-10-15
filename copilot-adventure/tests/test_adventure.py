import json
import tempfile
import unittest
from pathlib import Path

from adventure import Adventure, GameState
from story import START_SCENE, STORY


class SceneGraphTests(unittest.TestCase):
    def test_every_choice_target_exists_and_every_scene_is_reachable(self):
        for scene_id, scene in STORY.items():
            for choice in scene.get("choices", []):
                self.assertIn(
                    choice["target"],
                    STORY,
                    f"{scene_id} points to missing scene {choice['target']}",
                )

        reachable = set()
        pending = [START_SCENE]
        while pending:
            scene_id = pending.pop()
            if scene_id in reachable:
                continue
            reachable.add(scene_id)
            pending.extend(
                choice["target"] for choice in STORY[scene_id].get("choices", [])
            )
        self.assertEqual(reachable, set(STORY))

    def test_story_has_good_bad_and_secret_endings(self):
        ending_scenes = [scene for scene in STORY.values() if scene.get("ending")]
        endings = {scene["ending"] for scene in ending_scenes}
        self.assertGreaterEqual(len(ending_scenes), 4)
        self.assertTrue({"good", "bad", "secret"}.issubset(endings))


class InventoryTests(unittest.TestCase):
    def test_required_item_blocks_choice_until_collected(self):
        game = Adventure(state=GameState(scene="cave"))
        self.assertEqual(game.missing_items(game.current_scene["choices"][0]), ["brass_key"])
        self.assertFalse(game.choose(1))
        self.assertEqual(game.state.scene, "cave")

        game.state.inventory.append("brass_key")
        self.assertTrue(game.choose(1))
        self.assertEqual(game.state.scene, "vault")

    def test_choice_grants_item_once(self):
        game = Adventure(state=GameState(scene="market"))
        self.assertTrue(game.choose(1))
        self.assertEqual(game.state.inventory, ["brass_key"])
        game.state.scene = "market"
        self.assertTrue(game.choose(1))
        self.assertEqual(game.state.inventory, ["brass_key"])


class SaveLoadTests(unittest.TestCase):
    def test_save_load_round_trip(self):
        game = Adventure(state=GameState(scene="watchtower", inventory=["rope", "lantern"]))
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "progress.json"
            game.save(save_path)
            saved_data = json.loads(save_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_data["scene"], "watchtower")
            self.assertEqual(saved_data["inventory"], ["rope", "lantern"])

            restored = Adventure()
            restored.load(save_path)
            self.assertEqual(restored.state, game.state)

    def test_invalid_load_does_not_change_state(self):
        game = Adventure()
        original = game.state
        with tempfile.TemporaryDirectory() as directory:
            save_path = Path(directory) / "invalid.json"
            save_path.write_text('{"version": 1, "scene": "missing", "inventory": []}')
            with self.assertRaises(ValueError):
                game.load(save_path)
        self.assertEqual(game.state, original)


if __name__ == "__main__":
    unittest.main()
