#!/usr/bin/env python3
"""Validate exact Mojo compiler pins in each recipe dependency section."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SECTIONS = ("build", "host", "run")
COMPILER_REQUIREMENT = re.compile(r"^\s*-\s+mojo-compiler(?:\s|$)")
MAPPING_HEADER = re.compile(r"^(?P<indent> *)(?P<name>[A-Za-z0-9_-]+):\s*(?:#.*)?$")


class ValidationError(ValueError):
    """Raised when a recipe violates the compiler pin contract."""


def validate_recipe(recipe: str, expected_version: str = "1.0.0") -> None:
    """Require one exact compiler pin in build, host, and run, with no extras."""
    requirements_headers = 0
    section_headers = {section: 0 for section in SECTIONS}
    section_requirements: dict[str, list[tuple[int, str]]] = {
        section: [] for section in SECTIONS
    }
    all_compiler_requirements: list[tuple[int, str]] = []

    in_requirements = False
    active_section: str | None = None
    for line_number, line in enumerate(recipe.splitlines(), start=1):
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise ValidationError(f"line {line_number}: indentation must not use tabs")

        compiler_requirement = COMPILER_REQUIREMENT.match(line) is not None
        if compiler_requirement:
            all_compiler_requirements.append((line_number, line.strip()))

        header = MAPPING_HEADER.match(line)
        indent = len(line) - len(line.lstrip(" "))
        if header and indent == 0 and header.group("name") == "requirements":
            requirements_headers += 1
            in_requirements = True
            active_section = None
            continue

        stripped = line.strip()
        if (
            in_requirements
            and stripped
            and not stripped.startswith("#")
            and indent == 0
        ):
            in_requirements = False
            active_section = None

        if not in_requirements:
            continue

        if header and indent == 2:
            name = header.group("name")
            active_section = name if name in SECTIONS else None
            if active_section is not None:
                section_headers[active_section] += 1
            continue

        if compiler_requirement and indent == 4 and active_section is not None:
            section_requirements[active_section].append((line_number, line.strip()))

    if requirements_headers != 1:
        raise ValidationError(
            f"recipe must contain exactly one top-level requirements section; "
            f"found {requirements_headers}"
        )

    if len(all_compiler_requirements) != 3:
        locations = ", ".join(
            f"line {line_number}: {requirement}"
            for line_number, requirement in all_compiler_requirements
        )
        raise ValidationError(
            "recipe must contain exactly three total mojo-compiler requirement lines; "
            f"found {len(all_compiler_requirements)}"
            + (f" ({locations})" if locations else "")
        )

    expected_fields = ["-", "mojo-compiler", f"=={expected_version}"]
    for section in SECTIONS:
        if section_headers[section] != 1:
            raise ValidationError(
                f"requirements.{section} must appear exactly once; "
                f"found {section_headers[section]}"
            )
        requirements = section_requirements[section]
        if len(requirements) != 1:
            raise ValidationError(
                f"requirements.{section} must contain exactly one mojo-compiler "
                f"requirement; found {len(requirements)}"
            )
        line_number, requirement = requirements[0]
        if requirement.split() != expected_fields:
            raise ValidationError(
                f"line {line_number}: requirements.{section} must be exactly "
                f"'mojo-compiler =={expected_version}'; found {requirement!r}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("--expected-version", default="1.0.0")
    arguments = parser.parse_args(argv)

    try:
        recipe = arguments.recipe.read_text(encoding="utf-8")
        validate_recipe(recipe, arguments.expected_version)
    except (OSError, UnicodeError, ValidationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"Validated build/host/run mojo-compiler =={arguments.expected_version}: "
        f"{arguments.recipe}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
