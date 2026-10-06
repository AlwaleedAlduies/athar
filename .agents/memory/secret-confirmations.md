---
name: Secret confirmations
description: Validate required credential rotation without revealing the secret.
---

Treat a secure-form response saying a secret was added or confirmed as confirmation of its existence, not proof that an existing value was replaced.

**Why:** Existing-secret confirmations can retain the original value, including a publicly shared demo credential.

**How to apply:** When rotation is required, check the replacement against the known compromised credential and password policy inside application code. Report only pass/fail; never print the value. If repeated confirmations retain the old value, direct the user to edit and update the existing secret rather than opening the same confirmation form again.
