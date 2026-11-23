# Mahjong Wild Security Readiness (evidence checkpoint)
Date: 2026-11-24. Scope: 9dbit/Mahjong-legend and Railway project Mahjong Legend production. All checks performed in read-only mode except security branch/PR changes. This is **not** an independent penetration test or certification.

## Decision
**NO-GO for agent-wallet/real-value go-live.** Existing virtual-credit guest game remains a separate operating decision; do not equate service availability with a security assessment. No environment, wallet balances, game economics, seeds, credentials, schemas, or production branch were changed by this work.

## Verified evidence
- GitHub repo is **public**; default branch main. PR #16 `feat/agency-native-wallet-20261108` remains **OPEN/DRAFT/unmerged** with head `d75ea42af04bbd027fecc64408f7cb52d1d4cfdf`.
- Railway production web and worker are BOTH sourced directly from that draft branch/head rather than main; deployments `5207789c-d951-46bc-83e9-baebd74088bf` and `ede5e946-fff0-45c5-9ea5-8d336af53bd0` are SUCCESS. Postgres also online. No staged changes.
- Railway project has **production only**, no separate staging environment. Web and worker have **no persistent volumes**. PostgreSQL has a 5000 MB volume and private media bucket exists.
- Railway web/worker environment-variable **names** do not include `AGENCY_WALLET_MODE`, `MAHJONG_AGENCY_DB_PATH`, `AGENCY_WALLET_ORIGIN`, or `AGENCY_STUDIO_SYNC`. Therefore no evidence that opt-in native agency wallet is running on those services. Absence of a web persistent volume is a blocker **before enabling** native wallet, not proof of current lost transactions. Values of secrets were not requested or exported.
- PR #16 documentation explicitly requires a durable `/data` volume for SQLite/WAL native intent, one replica, sandbox wallet only, and rejects live mode. It describes synthetic credit tests, not real-value readiness.
- Source review shows Django `DEBUG=False`, session HttpOnly and production-conditioned Secure, restricted Studio permissions, CSRF middleware, same-origin checks for exempt public Spin requests, input bounds and hashed signed wallet HMAC. These are defenses, **not** proof against all attacks.
- GitHub Actions run [42464368122](https://github.com/9dbit/Mahjong-legend/actions/runs/42464368122) on PR #16 completed SUCCESS for its configured tests. This does not cover dependency CVEs, independent dynamic pen testing, physical backup, multi-region disaster recovery or regulatory acceptance.
- Actual Railway build logs show Dockerfile stages are used, despite builder metadata `RAILPACK`. No builder-mismatch finding is raised.

## Security changes proposed in this review
- `agency_runtime.py`: Native wallet refuses startup before creating SQLite if production has no `RAILWAY_VOLUME_MOUNT_PATH`, path is outside mounted volume, symlink escapes, or mount is missing. Prevents accidental ephemeral SQLite creation when activating agency mode.
- `tools/start_studio.py`: Prevents Studio worker role from accidentally booting a second native wallet web process.
- `tests/test_agency_native.py`: Five new regression cases for missing volume, wrong path, unmounted path, valid mounted path, and symlink escape.
- `.github/workflows/security.yml`: Read-only Python pip-audit and Studio npm audit for high severity dependency findings, with failing gates.
These changes are confined to a new audit branch and require GitHub PR review and green CI before any controlled promotion. They **do not turn on native wallet mode**.

## Remaining production gates (blocking)
1. **Release provenance (P0)**: merge/reconcile PR #16 after full review; protect main, require PR reviews and required tests, deploy exact signed/verified release SHA to staging first, then promote by controlled process. Never silently repoint existing production during audit.
2. **Environment isolation (P0)**: create separate staging services/database/bucket/keys/domain, plus *verified* mounted persistent volume for native intent; test restart, redeploy, volume detach, host loss and backup restoration. Avoid sharing production credentials or wallet accounts.
3. **Identity & API (P0)**: independent authorization/tenant-isolation review, MFA for publisher/admin, session fixation/expiry/logout, permission escalation, CSRF/CORS, replay and rate-limit abuse. Safe DAST only on explicitly approved staging; do not stress production.
4. **Wallet/ledger (P0)**: sustained concurrency under multi-node behavior (or explicitly single-node), outbox/reserve/settle replay, lost acknowledgements, recovered original intent, currency/scale/rounding, cross-tenant/idempotency keys, tamper-evident audit. No live balances changed as test.
5. **Software supply chain (P0)**: review dependency alerts, SAST, secrets scanning, image provenance/SBOM, build user privilege, vulnerable OS packages. Rotate any secrets **only** via a coordinated cutover, never by copying them into a public repo or report.
6. **Resilience/monitoring (P0)**: encrypted offsite PostgreSQL+private media+native-volume backups, retention, test isolated restore, RPO/RTO, alerts on rejected settlements/health, rollback rehearsals, denial-of-service controls and abuse monitoring.
7. **Economic, legal, and independent approval (P0)**: approved RNG/math and effective payout/rounding, external legal/regulatory review for any real-value product; external security sign-off separate from developer tests.

## Go-live rule
NO-GO until all P0 gates have reproducible dated receipts tied to one final code SHA and deployed staging artifacts, with independent reviewers and an authorized release decision. Guest virtual-credit operation must not be reclassified as real-value ready solely due to passing CI.

## Primary references
- [PR #16](https://github.com/9dbit/Mahjong-legend/pull/16)
- [Security patch branch](https://github.com/9dbit/Mahjong-legend/tree/security/native-storage-preflight-20261124)
- [Current branch CI](https://github.com/9dbit/Mahjong-legend/actions/runs/42464368122)
- [NATIVE_PLAYGROUND.md](https://github.com/9dbit/Mahjong-legend/blob/feat/agency-native-wallet-20261108/NATIVE_PLAYGROUND.md)
