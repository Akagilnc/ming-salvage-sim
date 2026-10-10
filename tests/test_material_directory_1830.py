"""#1830 S1：材料目录骨架与目录读取。

Seams: prepare_character_materials (directory + opening min set),
list_materials/read_material (API), CLI cwd/readonly flags, restore rebuild.
"""

from __future__ import annotations





def _active_minister(db, content, *, office_type=None):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if office_type and character.office_type != office_type:
            continue
        if db.characters.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")
