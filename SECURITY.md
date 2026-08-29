# Security Policy

## Supported Scope

Security reports are accepted for the active mainline of this repository and its public dependencies.

Priority areas:

- Authentication and authorization controls
- Per-client data boundaries and tenancy isolation
- Secret handling and credential exposure
- Delivery routing and recipient safety
- Replay artifact and log data leakage

## Reporting a Vulnerability

Please report vulnerabilities privately. Do not open public issues with exploit details.

Primary contact:

- Email: zariffromlatif@gmail.com
- Fallback: open a private advisory in the GitHub Security tab

Include:

- Affected component and file path
- Reproduction steps
- Impact assessment
- Suggested remediation (optional)

## Disclosure Rules

- No public disclosure before a fix is available.
- Maintainers will acknowledge receipt and triage severity.
- Critical issues should be patched first (credential leaks, auth bypass, client data exposure, misrouted delivery).

## Safe Harbor

Good-faith security research is welcome. Please avoid:

- Accessing real user/client data
- Disrupting availability
- Social engineering
- Any destructive testing
