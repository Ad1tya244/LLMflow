# Security policy

LLMFlow stores people's provider API keys, so security reports are taken seriously.

## Reporting a vulnerability

Please report it **privately**, not in a public issue:

- Use GitHub's private reporting: the repository's **Security** tab, then **Report a vulnerability**.

Include what you found, how to reproduce it, and what you think the impact is. Please do not
test against other people's workspaces, and do not publish details until it is fixed.

You can expect an acknowledgement and a fix or a clear answer as soon as the maintainer can
manage; this is a single-maintainer project.

## What is in scope

The gateway (`backend/`), the dashboard (`dashboard/`), and the deployment files in this
repository. How secrets are protected, the threat model, and the known limitations are described
in [docs/SECURITY.md](docs/SECURITY.md).

## Please never include real secrets in a report

Use dummy keys. If you accidentally exposed a real key while testing, revoke it at the provider.
