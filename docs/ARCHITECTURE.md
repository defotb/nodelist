# OTB Node Directory — System Architecture

## Overview

OutsideTheBox Node Directory is a multichain blockchain
network observation and visualization platform.

The system gathers peer information from distributed collectors,
combines observations, and publishes network information through
a public web interface.

Currently supported blockchains:

- Etho Protocol (ETHO)
- Etica (ETI)

## System Components

### 1. Blockchain Nodes

Blockchain nodes participate in their respective peer-to-peer
networks.

Connected peer information is collected from participating
observation sources.

### 2. Distributed Collectors

Collectors communicate with blockchain nodes and retrieve
network peer information.

Each registered collector has an assigned identity and
authentication credential.

Collectors submit observations to the central receiver.

Multiple collectors may observe the same network node.

### 3. Observation Receiver

The production observation receiver runs as:

    otb-node-receiver.service

Local endpoint:

    127.0.0.1:8766

Public requests are forwarded through Nginx.

The receiver authenticates collector submissions and
processes incoming blockchain observations.

Collector authorization must respect the current registration
status before accepting new observations.

### 4. Observation Storage

Submitted network observations are stored separately
from collector authentication credentials.

Observation data provides the input for the publisher.

Observations can become stale when collectors stop reporting
or previously discovered peers disappear.

### 5. Multichain Publisher

The publisher is managed by:

    otb-node-publisher.service
    otb-node-publisher.timer

The publisher processes stored observations and builds
public feeds for each supported blockchain.

It combines information from multiple collectors and
deduplicates observed nodes.

A network node independently observed by an authorized
collector should remain published even if another
collector is suspended or revoked.

### 6. Public Node Directory

Production website:

    https://nodelist.outsidethebox.top

The public interface allows visitors to select ETHO
or Etica and inspect available network observations.

The public directory does not require authentication.

Published feeds are served from:

    /var/www/nodelist.outsidethebox.top/feeds/

### 7. Collector Enrollment

The production enrollment service runs as:

    otb-enrollment.service

Local endpoint:

    127.0.0.1:8767

Enrollment manages collector registration information,
authentication tokens, invitations, and related status.

The registration database uses a shared filesystem
lock and recovery journal.

Important production paths:

    config/chains.json
    private/tokens.json
    private/invitations.json
    private/collector-status.json
    private/enroll.lock
    private/enroll-transaction.json

These private files are not part of the Git repository.

### 8. Administrator

The administrator is accessible through:

    https://nodelist.outsidethebox.top/admin/

The current administrator uses two authentication layers:

1. Nginx HTTP authentication
2. Application-level login and session authentication

The administration interface displays registered
collectors across ETHO and Etica.

Production-changing operations remain disabled until
the coordinated transaction integration is complete.

Planned management actions include:

- Approve
- Deny
- Suspend
- Enable
- Revoke

Administrator actions must respect enrollment locking,
transaction recovery, and audit requirements.

### 9. Pending Explorer

The Pending Explorer is intended to display provisional
or unconfirmed network information separately from
approved production observations.

Pending information must be clearly labeled as
unconfirmed.

The public Pending Explorer is part of the planned
unified v2.5.0 integration.

## Data Flow

    ETHO / Etica blockchain networks
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
          Public JSON feeds
                  |
                  v
          Public Node Directory

Collector enrollment and administration manage
authorization alongside the observation pipeline.

## Collector Lifecycle

The intended collector lifecycle includes:

    Invitation / Enrollment
              |
              v
        Pending approval
              |
              v
           Enabled
          /       \
         v         v
     Suspended   Revoked
         |
         v
       Enabled

Administrative changes must be reflected by the
receiver and publisher.

Suspending or revoking a collector must not remove
network nodes independently observed by other
authorized collectors.

## Transaction Safety

Collector registration changes rely on:

- A shared enrollment lock
- A recovery journal
- Atomic file replacement
- Registry consistency validation
- Administrative audit records

Administrative operations must not bypass
the enrollment service's recovery protections.

## Security Boundaries

The public website must not expose:

- Collector authentication tokens
- Administrator credentials
- Enrollment invitation secrets
- Private registration records
- Session secrets
- Recovery journals

Public observations may include blockchain node
addresses and network relationships.

The project must provide appropriate disclosure
to collectors before publishing identifying
observation information.

## Current Recovery Considerations

Some original production Python source files were
accidentally truncated during maintenance.

The receiver, publisher, and enrollment server
have been restored operationally using preserved
Python 3.8 bytecode and recovery launchers.

All three services have been verified operationally,
including successful restart tests of the receiver
and enrollment server.

The original maintainable source code still needs
to be recovered or reconstructed.

Recovery bytecode and private runtime data must
remain outside the public Git repository.

## Planned Release

The target unified release is:

    v2.5.0

This release is intended to align:

- Public Node Directory
- Pending Explorer
- Administrator

The version should not be considered released until
integration and production testing are complete.
