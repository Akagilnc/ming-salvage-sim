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
        if db.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


    # 路径由列目录取得；人读 INDEX 不承担路径解析契约。
    # 大理寺 01a0f1f4 裁定：不重调生产渲染器逐字比正文（与被调函数同进同出，
    # 只证接线），也不扫描名册正文推断成员身份（人读正文不是结构化记录身份，
    # 一次合法换行即假红）。
