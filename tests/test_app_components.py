import unittest

from tp_app.catalogue_mapper import CatalogueMapper
from tp_app.openai_access import OpenAIKeyManager


class OpenAIKeyManagerTests(unittest.TestCase):
    def test_personal_key_takes_precedence(self):
        status = OpenAIKeyManager.choose(" personal-key ", "deployment-key")
        self.assertEqual(status.value, "personal-key")
        self.assertEqual(status.source, "personal")

    def test_deployment_key_is_a_fallback(self):
        status = OpenAIKeyManager.choose("", "deployment-key")
        self.assertEqual(status.value, "deployment-key")
        self.assertEqual(status.source, "deployment")

    def test_blank_keys_disable_ai(self):
        status = OpenAIKeyManager.choose(" ", "")
        self.assertEqual(status.value, "")
        self.assertEqual(status.source, "missing")


class CatalogueMapperTests(unittest.TestCase):
    def test_active_and_timing_remain_independent(self):
        catalog = {
            "version": 3,
            "conducts": [
                {
                    "conduct_id": "combat_circuit",
                    "lesson_plan_name": "Combat Circuit",
                    "active": True,
                    "timing": None,
                    "preparation": {},
                }
            ],
        }
        mapper = CatalogueMapper()
        frame = mapper.to_frame(catalog)
        self.assertTrue(bool(frame.loc[0, "active"]))
        self.assertEqual(frame.loc[0, "timing"], "None")
        rebuilt = mapper.from_frame(frame, catalog)
        self.assertTrue(rebuilt["conducts"][0]["active"])
        self.assertIsNone(rebuilt["conducts"][0]["timing"])


if __name__ == "__main__":
    unittest.main()
