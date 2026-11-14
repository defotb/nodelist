# OutsideTheBox Node Directory

**OTB Node Directory** is a multichain blockchain node discovery,
monitoring, and visualization system developed by OutsideTheBox.

Live website: https://nodelist.outsidethebox.top

## Supported Blockchains

- **Etho Protocol (ETHO)**
- **Etica (ETI)**

The architecture is designed to accommodate additional blockchains.

## Project Overview

OTB Node Directory gathers peer observations from distributed blockchain
collectors and combines them into publicly accessible network views.

The system consists of:

### Public Node Directory

Displays discovered blockchain nodes, connected peers, and network
relationships.

Visitors can select a blockchain without creating an account.

### Distributed Collectors

Collectors gather peer information from blockchain nodes and submit
observations to the central receiver.

Observations from multiple collectors are combined to improve network
visibility and reduce dependence on any single observation source.

### Observation Receiver

Accepts authenticated observations from registered collectors.

The receiver validates incoming submissions before storing them for
publication.

### Publisher

Processes collected observations and generates the public network feeds.

Nodes observed independently by multiple collectors are deduplicated.

### Collector Enrollment

Manages collector registrations and credentials.

Enrollment operations use file locking and transaction recovery to
protect the registration database.

### Pending Explorer

A separate view for observations awaiting confirmation or approval.

Pending information must be clearly identified as unconfirmed and
should not be treated as authoritative network data.

### Administration

A protected administration interface for reviewing collectors and
managing their registration status.

Administrator access uses two authentication layers:

1. Nginx HTTP authentication.
2. Application-level administrator authentication.

Administrative operations are designed to use an auditable transaction
system and shared enrollment locking.

## Network Architecture

The main data flow is:

    Blockchain nodes
          |
          v
    Distributed collectors
          |
          v
    Authenticated receiver
          |
          v
    Observation storage
          |
          v
    Multichain publisher
          |
          v
    Public Node Directory

Collector enrollment and administration operate alongside this pipeline.

## Technology

The project uses:

- Python 3
- Flask for the administrator API
- Nginx
- systemd services and timers
- HTML, CSS, and JavaScript
- JSON observation feeds

## Project Status

The public ETHO and Etica directories are operational.

The administrator can authenticate and display production collector
registrations. Production-changing administrator operations remain
disabled while integration and testing are completed.

The pending explorer and unified application presentation are still
being integrated.

The planned unified release is **v2.5.0**.

### Source Recovery Notice

Some production Python services are temporarily operating through
recovery launchers that execute preserved Python 3.8 bytecode.

Those launchers are not a replacement for maintainable source code.
The affected source files must be restored before this repository
can serve as a complete source-based disaster-recovery backup.

Private recovery bytecode is intentionally excluded from Git.

## Security and Privacy

This repository must never contain:

- Collector authentication tokens
- Administrator passwords or password hashes
- Invitation secrets
- Private enrollment or registration databases
- Production observation data containing sensitive information
- Private keys, environment secrets, or recovery journals
- Server backups or private recovery artifacts

Public network observations may expose node IP addresses and network
relationships. Collector enrollment must provide appropriate disclosure
before publishing identifying network information.

See [SECURITY.md](SECURITY.md) for additional information.

## Documentation

Additional documentation is maintained in the `docs/` directory.

Deployment instructions, architecture details, and recovery procedures
will be expanded as the project is prepared for a stable release.

## Development

Development and testing should be performed with isolated registration
databases and observation feeds.

Production collector registrations must not be used as test fixtures
containing real credentials.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Licensing terms have not yet been selected.

Until a license is published, no open-source license is granted by
this repository.

## Project

Developed by **OutsideTheBox**.

GitHub: https://github.com/defotb/nodelist
