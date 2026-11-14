# OTB Node Directory — Deployment Guide

## Overview

This document describes the current production deployment
of OutsideTheBox Node Directory.

The deployment supports:

- Etho Protocol (ETHO)
- Etica (ETI)

Production website:

https://nodelist.outsidethebox.top

## Server Environment

The current Node Directory application runs on an
Ubuntu Linux server using:

- Python 3.8
- Nginx
- systemd
- Flask for administrator functionality
- JSON-based collector registration and observations

The application directory is:

    /home/def/otb-node-directory

The public website directory is:

    /var/www/nodelist.outsidethebox.top

## Production Services

### Observation Receiver

Service:

    otb-node-receiver.service

Entry point:

    /home/def/otb-node-directory/receiver.py

Local endpoint:

    127.0.0.1:8766

Receives authenticated observations from distributed
blockchain collectors.

### Enrollment Server

Service:

    otb-enrollment.service

Entry point:

    /home/def/otb-node-directory/otb-enrollment-server.py

Local endpoint:

    127.0.0.1:8767

Handles collector enrollment and registration operations.

### Multichain Publisher

Service:

    otb-node-publisher.service

Timer:

    otb-node-publisher.timer

Publisher entry point:

    /home/def/otb-node-directory/publish.py

The publisher service also executes:

    publish_chains.py

The publisher periodically updates public ETHO and
Etica observation feeds.

### Administrator

Service:

    otb-admin-preview.service

The current administrator is accessed through:

    https://nodelist.outsidethebox.top/admin/

The administrator is protected by Nginx HTTP authentication
and an application-level login.

The administrator currently displays real production
collector registrations in read-only mode.

Production-changing operations must remain disabled
until their deployment and integration are verified.

## Public Feeds

Published observations are stored under:

    /var/www/nodelist.outsidethebox.top/feeds/

Current blockchain feed directories include:

    feeds/etho/
    feeds/etica/

These files are generated runtime data and should not
be committed to Git.

## Private Configuration

Production configuration includes:

    config/chains.json
    private/tokens.json
    private/invitations.json
    private/collector-status.json
    private/enroll.lock
    private/enroll-transaction.json

The recovery journal may be absent when no transaction
is pending.

These files contain operational or sensitive information.
They must not be committed to a public Git repository.

Use sanitized example files for documentation.

## Nginx

Nginx provides public HTTPS access to the Node Directory.

Its responsibilities include:

- Serving the public frontend
- Serving published observation feeds
- Proxying authenticated collector submissions
- Proxying enrollment requests
- Protecting the administrator interface

The production virtual host is configured under:

    /etc/nginx/sites-available/

Administrator authentication configuration must
remain outside the public repository.

## Service Inspection

Check service status:

    systemctl is-active otb-node-receiver.service
    systemctl is-active otb-enrollment.service
    systemctl is-active otb-node-publisher.timer
    systemctl is-active otb-admin-preview.service

Inspect recent logs:

    journalctl -u otb-node-receiver.service -n 30 --no-pager

    journalctl -u otb-enrollment.service -n 30 --no-pager

    journalctl -u otb-node-publisher.service -n 30 --no-pager

    journalctl -u otb-admin-preview.service -n 30 --no-pager

## Safe Deployment Procedure

Before modifying a production service:

1. Identify the exact source file executed by systemd.
2. Verify the replacement code and its dependencies.
3. Check for incomplete enrollment transactions.
4. Create a recoverable backup outside the Git repository.
5. Test Python syntax and isolated functionality.
6. Confirm the replacement contains no production secrets.
7. Deploy one service at a time.
8. Verify service startup and logs.
9. Verify the corresponding public functionality.
10. Retain a working rollback copy.

Do not restart multiple critical services simultaneously
during routine deployment.

## Collector Transaction Safety

Changes to collector registration must coordinate with:

    private/enroll.lock

and:

    private/enroll-transaction.json

Administrative actions must not bypass the enrollment
transaction and recovery mechanism.

A suspended or revoked collector must no longer be
authorized to submit observations.

The publisher must exclude unauthorized collector
contributions without removing independently observed
network nodes.

## Current Source Recovery Limitation

The original receiver, publisher, and enrollment Python
source files were accidentally truncated.

Operational recovery was completed using preserved
Python 3.8 bytecode and small Python launchers.

Recovered launcher locations:

    receiver.py
    publish.py
    otb-enrollment-server.py

The bytecode is stored outside Git tracking in:

    otb-bytecode-recovery/

The receiver and enrollment server successfully
restarted using these recovered launchers.

The publisher successfully executed using its
recovered bytecode.

These launchers require compatible Python bytecode
and must not be treated as restored source code.

The original maintainable source must be reconstructed
or recovered before depending on GitHub alone for
complete disaster recovery.

Do not delete the preserved bytecode during cleanup.

## GitHub Deployment Policy

The GitHub repository contains reviewed project source
and documentation only.

Do not commit:

- Production credentials or authentication hashes
- Collector tokens
- Private registration data
- Runtime observations
- Backup archives
- Recovery journals
- Bytecode recovery files
- Outdated development snapshots

All new files must pass a security review before
being added to Git.

## Release Status

The current system is being prepared for a unified
v2.5.0 release covering:

- Public Node Directory
- Pending Explorer
- Administrator

Version v2.5.0 should not be considered released until
all required components are integrated and verified.
