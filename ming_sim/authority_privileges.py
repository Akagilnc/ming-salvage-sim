"""ADR 0071 first-batch held-authority privileges — single import-safe source."""

# Ordered tuple is the sole machine enum; CHECK SQL and apply validation both consume it.
AUTHORITY_PRIVILEGES = (
    "尚方剑密授",
    "便宜行事",
    "专差督办",
    "新机构专办",
)
AUTHORITY_PRIVILEGE_SET = frozenset(AUTHORITY_PRIVILEGES)
AUTHORITY_PRIVILEGE_SQL_IN = ",".join(
    f"'{name}'" for name in AUTHORITY_PRIVILEGES
)
