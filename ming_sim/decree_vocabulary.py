"""#471 皇帝动作在案卷层的 canonical 受控词表。"""

DOSSIER_ACTION_TYPES = frozenset({
    "policy", "appointment", "acting_appointment",
    "assignment", "military_order",
    "grant_allocation", "authorization", "secret_authorization",
    "secret_investigation", "protection",
    "strategy_selection", "approve_reject",
    "secret_order", "special_decree",
    "revoke_decree", "punishment", "pacification", "referral",
    "revoke_authority", "dismiss_assignment",
})

DIRECTIVE_ACTION_TYPES = DOSSIER_ACTION_TYPES - {"appointment", "secret_order"}
