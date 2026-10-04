"""Test setup through the live 4a identity-material producer."""

from dataclasses import replace

from ming_sim.materials import list_materials, prepare_world_materials, write_identity_materials


def prepare_identity_materials(db, state, character, *, dest_root=None):
    prepared = prepare_world_materials(db, state, dest_root=dest_root)
    (identity_index,) = write_identity_materials(prepared, db, state, [character.name])
    root = (prepared.root / identity_index).parent
    return replace(prepared, root=root, index_lines=tuple(list_materials(root)))
