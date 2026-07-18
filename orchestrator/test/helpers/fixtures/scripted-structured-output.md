# #899 scripted structured-output harness (thin)

Emit a corrected `<{{TAG}}>` JSON block only.

No method, no recovery loop, no cargo schema. Sandcastle owns Output.object
maxRetries; this fixture is a versioned promptFile so tests never pass an
inline `prompt` to `sc.run` (orchestrator/CLAUDE.md).
