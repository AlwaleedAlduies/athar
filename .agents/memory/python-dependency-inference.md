---
name: Python dependency inference
description: Avoid an incorrect inferred package when installing this project's Python dependencies.
---

Replit's package installation callback can infer and add the obsolete `docx`
package even when only other dependencies were requested. This project's
`docx` imports belong to `python-docx`, not the separate `docx` distribution.

**Why:** During imported-project setup, installing both the locked dependencies
and the test dependency unexpectedly added `docx` and duplicate requirements.
Uninstalling `docx` preserved the working `python-docx` imports and test suite.

**How to apply:** After package installations, inspect the requirements diff,
remove accidentally inferred `docx` through the package tool, and preserve the
original separation between runtime requirements and test requirements.