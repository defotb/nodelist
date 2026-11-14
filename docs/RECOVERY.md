# OTB Node Directory — Recovery Guide

## Purpose

This document records the November 13, 2026 source-file
recovery and the precautions required to maintain a
recoverable OTB Node Directory installation.

## Incident Summary

During terminal maintenance, several Python source files
were accidentally truncated to zero bytes.

The affected original production files were:

    receiver.py
    publish.py
    otb-enrollment-server.py

The corresponding production compatibility candidates
and their temporary backup copies were also affected.

The incident did not establish any damage to the
production collector registration database.

## Preserved Python Bytecode

Python 3.8 bytecode files survived in the project's
__pycache__ directories.

Six files were copied into:

    otb-bytecode-recovery/

These include original production and compatibility
candidate bytecode for:

- Observation receiver
- Multichain publisher
- Collector enrollment server

The original compiled bytecode was validated and
preserved before recovery operations began.

This recovery directory must remain private and
must not be committed to GitHub.

## Original Production Recovery

The empty production Python files were replaced with
small launchers that execute the preserved original
Python 3.8 bytecode.

Recovered entry points:

    receiver.py
    publish.py
    otb-enrollment-server.py

The launchers preserve the original Python execution
context sufficiently for the tested services to operate.

They depend on the saved bytecode remaining available.

## Verification Results

### Publisher

The recovered publisher successfully executed and
updated ETHO and Etica network feeds.

The publishing command returned exit status zero.

The publisher systemd timer remained active.

### Receiver

The recovered receiver successfully restarted through
systemd.

It listened on:

    127.0.0.1:8766

After restarting, it accepted observations from
registered ETHO and Etica collectors.

### Enrollment Server

The recovered enrollment server successfully restarted
through systemd.

It listened on:

    127.0.0.1:8767

Startup logs reported no errors.

## Current Recovery Status

The original production services are operationally
recovered.

However, the original maintainable Python source
has not yet been restored.

The production compatibility candidates also require
source recovery or reconstruction.

A functioning bytecode launcher does not provide
editable application source.

## Important Limitations

The bytecode recovery depends on a compatible
Python interpreter.

The current recovered bytecode uses Python 3.8.

Upgrading or replacing Python may prevent the
recovered applications from starting.

A GitHub backup containing only the recovery launchers
would not be sufficient to reconstruct these services
without the privately preserved bytecode.

## Recovery Precautions

Until maintainable source is restored:

1. Do not delete otb-bytecode-recovery/.
2. Do not remove the preserved compiled bytecode.
3. Do not upgrade Python without testing compatibility.
4. Do not replace the recovered launchers blindly.
5. Preserve the existing production configuration.
6. Test source replacements in isolation.
7. Keep private recovery copies outside GitHub.
8. Avoid restarting multiple critical services together.

## Service Status Checks

Receiver:

    systemctl is-active otb-node-receiver.service

Enrollment:

    systemctl is-active otb-enrollment.service

Publisher timer:

    systemctl is-active otb-node-publisher.timer

Administrator:

    systemctl is-active otb-admin-preview.service

Inspect service logs with:

    journalctl -u SERVICE_NAME -n 30 --no-pager

## Public Feed Checks

Production website:

    https://nodelist.outsidethebox.top

Published blockchain feeds are located under:

    /var/www/nodelist.outsidethebox.top/feeds/

Verify that generated feeds continue updating rather
than merely remaining accessible as stale files.

## Registration Recovery

Collector registration changes use:

    private/enroll.lock

and:

    private/enroll-transaction.json

The journal may be absent when no transaction is pending.

Do not delete an outstanding recovery journal to
force an enrollment or administrator operation.

Use the application recovery mechanism.

## GitHub Backup Scope

The public Git repository is intended to store:

- Reviewed, maintainable application source
- Public frontend source
- Non-secret configuration examples
- Project documentation
- Development and deployment instructions

It must exclude:

- Production registration credentials
- Administrator passwords and hashes
- Runtime observations
- Private server configuration
- Recovery bytecode
- Private backup archives
- Transaction journals

GitHub should not be treated as the only backup
of the running installation.

## Remaining Work

To complete source recovery:

1. Recover or reconstruct maintainable Python source.
2. Compare recovered behavior against the working services.
3. Test reconstructed services in isolation.
4. Verify collector authentication and enrollment recovery.
5. Deploy reviewed replacements one service at a time.
6. Confirm successful service restarts.
7. Commit only reviewed, credential-free source to GitHub.
8. Preserve an independent private recovery backup.

## Future Prevention

Use Git for version control of reviewed source.

Maintain separate protected backups for private
configuration, registration data, and operational
recovery materials.

Before deploying changes:

- Check file sizes.
- Verify syntax.
- Confirm the intended source path.
- Save a rollback copy.
- Test one component at a time.

Avoid pasting complete terminal transcripts into
an interactive shell.

Terminal prompts and output may contain characters
that Bash interprets as commands or redirections.

## Release Considerations

The unified v2.5.0 release should not be considered
complete until the original services and compatibility
components have maintainable, tested source code.

Operational recovery and source recovery are
separate milestones.
