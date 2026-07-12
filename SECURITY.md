# Security Policy

## Supported versions

This is an early-stage proof of concept. Only the latest commit on `main` receives security fixes. There are no published releases yet.

## Reporting a vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Report security concerns privately by opening a [GitHub Security Advisory](https://github.com/advisories) against this repository, or by emailing the maintainers through the contact channel configured on the repository's GitHub profile.

Include:

- Description of the vulnerability and potential impact
- Steps to reproduce or a proof of concept
- Affected components (if known)
- Suggested remediation (optional)

You should receive an acknowledgment within **5 business days**. We will work with you to understand and address the issue before any public disclosure.

## Scope

This POC deliberately excludes production security controls (authentication, authorization, encryption at rest, etc.) — see the spec non-goals. Reports about missing production hardening in the POC itself are expected and will be triaged as informational unless they introduce real risk in a deployed demo environment.

Please do report:

- Accidental inclusion of real credentials, API keys, or PII in the repository
- Injection or remote code execution in runnable components
- Dependency vulnerabilities with a clear exploit path in this project

## Code of conduct

Security researchers are expected to follow responsible disclosure practices and the [Code of Conduct](CODE_OF_CONDUCT.md).
