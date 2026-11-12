# Runbooks

| Runbook | Use it when |
|---|---|
| [deploy.md](deploy.md) | Setting up staging/production for the first time; every release; rollback |
| [backup-restore.md](backup-restore.md) | Restoring data (point in time, accidental deletion); the quarterly restore drill |
| [incident-response.md](incident-response.md) | An alarm fires; a suspected data breach or security incident |
| [observability.md](observability.md) | What is measured, where to look, suggested alert rules |
| [load-testing.md](load-testing.md) | Before launch and after major changes: capacity targets and how to measure |
| [secrets-rotation.md](secrets-rotation.md) | Rotating passwords, tokens and keys; after someone leaves |

> **Status (2026-11-12):** these procedures are written against the Terraform in `infra/terraform`, which has been validated but **not yet applied** to an AWS account. Steps marked ⚠ have not been exercised against real infrastructure.
