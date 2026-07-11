Use the bash tool exactly once with this command:

```bash
printf '%s\n' '{{NONCE}}' > '{{NONCE_FILE}}'
```

After the tool returns successfully, emit `ROUTE_SMOKE_COMPLETE`.
