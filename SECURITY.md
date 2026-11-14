# Security Policy

## Project Security

OutsideTheBox Node Directory collects blockchain network observations
and operates authenticated collector enrollment and administration
services.

Security is an important part of the project's design.

## Supported Versions

Security maintenance currently focuses on the active production
deployment and the upcoming unified v2.5.0 release.

Older development versions and archived prototypes are not supported.

## Reporting Vulnerabilities

Please report security vulnerabilities privately.

GitHub repository:
https://github.com/defotb/nodelist

Use GitHub's private vulnerability reporting feature if it is enabled
for this repository.

If private reporting is unavailable, open a GitHub issue requesting
a private contact method without disclosing vulnerability details.

Do not publish working exploits, authentication credentials, or
sensitive server information in public issues.

## Repository Restrictions

The following information must never be committed:

- Administrator passwords or password hashes
- Collector authentication tokens
- Enrollment invitation secrets
- SSH keys or other private keys
- API keys and access credentials
- Production registration databases
- Private configuration containing credentials
- Authentication session secrets
- Recovery journals containing private registration data
- Production observation archives
- Server backups, database dumps, or recovery bytecode

Use sanitized examples when documenting configuration formats.

## Administrator Security

The administration interface uses two authentication layers:

1. Nginx HTTP authentication
2. Application-level administrator authentication

Administrative operations should require authenticated sessions,
appropriate request validation, and audit records.

Production-changing actions must not be enabled until their
transaction and recovery mechanisms have been verified.

## Collector Security

Collector submissions require authentication.

Suspended or revoked collectors must not be allowed to submit
new observations.

Collector credentials must never appear in publicly accessible
feeds or administrator API responses.

## Data Integrity

Registration modifications must respect the shared enrollment
locking and recovery journal.

Avoid direct edits to production registration files while the
enrollment service is active.

Publisher and receiver changes must be tested for consistency
with collector registration status.

## Network Privacy

Public node observations may include:

- Node IP addresses
- Network endpoints
- Blockchain peer relationships
- Collector identifiers

Collectors should be informed of what information will be
published before enrollment.

Never publish private collector credentials.

## Development Practices

- Use isolated databases for tests.
- Review changes before production deployment.
- Keep recoverable backups outside the public Git repository.
- Check staged Git files for secrets before committing.
- Never use production credentials in example configuration.
- Avoid logging passwords, tokens, or session cookies.
- Document security-sensitive deployment changes.

## Credential Exposure

If credentials are accidentally committed:

1. Treat the exposed credentials as compromised.
2. Revoke or rotate them immediately.
3. Remove sensitive material from the repository and its history.
4. Check access logs for suspicious activity.
5. Review affected services and collector registrations.

Deleting a file in a later commit does not remove it from Git history.

## Recovery

Production recovery materials must be stored securely outside the
public repository.

Bytecode recovery launchers are temporary operational measures,
not substitutes for reviewed, maintainable source code.
