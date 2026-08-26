# Security Policy

DevDoctor runs on your machine, reads arbitrary directories, and generates and
(on your confirmation) executes cleanup commands. We take its safety guarantees
seriously.

## Reporting a vulnerability

**Please do not report security issues in public GitHub issues.**

Use GitHub's private vulnerability reporting instead:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Describe the issue, the impact, and steps to reproduce.

This keeps the report private until a fix is available. We aim to acknowledge
reports within a few days.

If you can't use private reporting, open a minimal public issue that says only
"security issue, please enable a private channel" — without details — and we'll
follow up.

## What we consider in scope

DevDoctor's threat model is a **local, single-user developer tool**. The most
valuable reports involve cases where the tool could do something the user didn't
intend, especially:

- **Command injection** into a generated cleanup script or the interactive
  cleanup path (e.g. via a crafted file or directory name on disk).
- **Path handling** that deletes, reads, or writes outside the intended target
  (traversal, unexpected symlink following, over-broad globs).
- **Wrong risk labels** — a provider that marks real user data (uploads, chat
  history, generated output, databases) as `safe`/`reclaimable` instead of
  `dangerous`.
- **Terminal or output injection** via attacker-controlled names surfaced in the
  CLI or web UI.

Reports about remote attackers or other local users on a shared machine are
generally out of scope, since anyone in that position can already run the same
destructive commands directly — but tell us anyway if something surprises you.

## Supported versions

DevDoctor is pre-1.0 and ships fixes on the `main` branch. Please test against
the latest `main` before reporting.
