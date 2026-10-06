---
name: Backup verification
description: Avoid false equality when verifying a cross-database restore.
---

Verify restored backup data with native Python field values rather than comparing JSON exports.

**Why:** Django's default JSON encoder truncates datetime microseconds to milliseconds. Comparing JSON exported from both databases can hide the loss because both representations are rounded the same way.

**How to apply:** For future imports or restore checks, compare native-value serialization, normalize many-to-many ordering and natural-key relationships, and exclude only the intentional security changes from equality checks.
