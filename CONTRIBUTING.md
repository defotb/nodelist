# Contributing to OTB Node Directory

Thank you for your interest in OutsideTheBox Node Directory.

The project provides multichain blockchain node discovery,
collector enrollment, network observation publishing, and
administration tools.

## Project Repository

https://github.com/defotb/nodelist

## Supported Networks

The current deployment supports:

- Etho Protocol (ETHO)
- Etica (ETI)

Support for additional blockchains may be added later.

## Development Guidelines

### Keep Changes Focused

Prefer small, independently testable changes.

Avoid combining unrelated modifications into a single pull request.

### Protect Production Services

Development and testing must not modify the production collector
database, authentication files, or published observations.

Use isolated test environments and synthetic credentials.

### Preserve Data Integrity

Changes to enrollment and administrator transactions must respect:

- Shared enrollment locking
- Transaction recovery journals
- Collector status validation
- Atomic file updates
- Audit records

Never bypass these protections to simplify development.

### Receiver and Publisher Changes

Changes must preserve compatibility between the observation receiver,
collector status registry, and public publisher.

Suspended and revoked collectors must be excluded appropriately.

Network nodes independently observed by other authorized collectors
must remain available.

### Authentication

Never commit:

- Administrator credentials
- Collector tokens
- Session secrets
- Private keys
- Production registration files

Use sanitized examples where configuration documentation is needed.

## Testing

Before submitting changes:

1. Verify Python syntax.
2. Test against an isolated registration database.
3. Check enrollment and transaction recovery.
4. Verify collector status handling.
5. Confirm public feeds contain no credentials.
6. Review changed files for sensitive information.

Do not use actual production tokens in tests.

## Pull Requests

Pull requests should include:

- A description of the change
- The reason for the change
- Relevant testing results
- Any deployment considerations
- Any compatibility or security implications

Changes affecting production services should include a rollback plan.

## Coding Practices

### Python

- Use descriptive function and variable names.
- Handle filesystem and JSON errors explicitly.
- Preserve atomic writes where required.
- Avoid unnecessary external dependencies.
- Keep authentication and transaction logic auditable.

### Frontend

- Maintain support for desktop and mobile layouts.
- Preserve light and dark theme compatibility.
- Follow existing OutsideTheBox branding.
- Keep public network information accessible without login.
- Clearly distinguish pending observations from approved data.

### Documentation

Update documentation when changing:

- Service architecture
- Deployment instructions
- Collector registration formats
- Administrative operations
- Public API behavior
- Security-sensitive configuration

## Reporting Problems

Use GitHub Issues for ordinary bugs and feature requests.

For security vulnerabilities, follow the private reporting
instructions in SECURITY.md.

## Releases

The project is preparing a unified v2.5.0 release.

Version numbers should reflect verified functionality, not merely
the completion of individual development components.

## Licensing

No open-source license has been selected yet.

Contributions do not change the repository's licensing terms.
Contact the repository owner before submitting substantial
contributions that require a licensing agreement.
