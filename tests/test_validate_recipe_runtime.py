from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_recipe_runtime", ROOT / "scripts" / "validate_recipe_runtime.py"
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


VALID_RECIPE = """\
requirements:
  build:
    - mojo-compiler ==1.0.0
  host:
    - mojo-compiler ==1.0.0
  run:
    - mojo-compiler ==1.0.0
"""


class RecipeRuntimeTests(unittest.TestCase):
    def test_accepts_one_exact_pin_in_each_required_section(self) -> None:
        validator.validate_recipe(VALID_RECIPE)

    def test_rejects_weaker_build_pin(self) -> None:
        recipe = VALID_RECIPE.replace(
            "    - mojo-compiler ==1.0.0", "    - mojo-compiler >=1.0.0", 1
        )
        with self.assertRaisesRegex(validator.ValidationError, "requirements.build"):
            validator.validate_recipe(recipe)

    def test_rejects_three_exact_pins_in_one_section(self) -> None:
        recipe = """\
requirements:
  build:
  host:
  run:
    - mojo-compiler ==1.0.0
    - mojo-compiler ==1.0.0
    - mojo-compiler ==1.0.0
"""
        with self.assertRaisesRegex(validator.ValidationError, "requirements.build"):
            validator.validate_recipe(recipe)

    def test_rejects_extra_compiler_requirement(self) -> None:
        recipe = VALID_RECIPE + "tests:\n  - mojo-compiler ==1.0.0\n"
        with self.assertRaisesRegex(validator.ValidationError, "exactly three total"):
            validator.validate_recipe(recipe)

    def test_rejects_missing_required_section(self) -> None:
        recipe = VALID_RECIPE.replace("  host:\n", "  test:\n")
        with self.assertRaisesRegex(validator.ValidationError, "requirements.host"):
            validator.validate_recipe(recipe)


if __name__ == "__main__":
    unittest.main()
