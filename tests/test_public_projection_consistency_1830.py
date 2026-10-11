"""#1830 S1：同一公开记录经场景／单人／世界三类目录的准入一致（共用读侧契约）。

现象（两轮）：其一，场景目录的 _write_one_present_person 曾自行逐条写 公开说法/，
与 _write_public_by_month 的邸报排除门分叉；其二，改走共用入口后，单人目录仍留一份
render_character_knowledge 的整体重投影 人物/<名>/见闻.txt——world.public 把公开层
正文再拼一遍，public_events/events 又逐条重述，于是同一条邸报同时可经
公开说法/邸报/ 与 见闻.txt 读到。公开材料因此存在非既定重复载体。

契约面：来源身份、列目录的载体路径集合、载体归属、API 与文件树一致性；终端文件
及两种读取入口保留独立输入原文，不规定标题／正文分隔符、记录顺序或拼接
换行。原文存在不替代 source_id 的准入证明，也不证明同正文记录的出现次数。
"""

from __future__ import annotations



def _active_minister(db, content):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if db.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")
