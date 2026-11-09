# Native environment isolation, recovery and release review

Date: 2026-11-10. Scope: Soft Tech dedicated native provider runtime only.
The operator and Playground repositories/services are unchanged. This is engineering
qualification evidence, not an independent security, RNG or jurisdiction certificate.

## Deployment contract

- `AGENCY_ENVIRONMENT`: `sandbox`, `preproduction`, or `production`.
- `AGENCY_DEPLOYMENT_ID`: immutable native service identity. Required outside sandbox.
- `AGENCY_CORE_DEPLOYMENT_ID`: immutable Core audience. Required outside sandbox.
- `AGENCY_WALLET_MODE=sandbox` still means the provider-managed test wallet adapter;
  it does not choose the environment. Separate services, volumes, credentials,
  Core URLs and keys must be provisioned for every environment.
- Production starts quarantined and returns `423 PRODUCTION_RELEASE_GATES_PENDING`
  before launch/play or any wallet transaction. No environment variable unlocks it.
- Every native process with Railway project/service/deployment context requires an
  existing absolute Railway volume mount, including sandbox. Missing mount aborts
  before directory/database creation or restore; local test contexts remain usable.
- Native SQLite contains an immutable identity table. Foreign identity fails in a
  read-only preflight before WAL/schema writes. Unbound legacy DBs may only migrate
  in sandbox. A DB outside the real persistent mount is rejected.
- Health includes `deployment_identity`; `physical_isolation_verified:false` is
  deliberate because an application cannot prove its infrastructure inventory.
- Existing sandbox deployments can use legacy v1 while no Core audience is set.
  Once an audience is configured, v2 is mandatory, including in sandbox. Changing
  the identity invalidates launch cookie namespaces and requires a fresh launch.

Agency v2 headers: `X-Agency-Version: 2`, `X-Agency-Environment`,
`X-Agency-Audience` plus existing key/timestamp/nonce/signature. HMAC input is:

```
agency.v2
<environment>
<core deployment ID>
POST
<exact path and query>
<Unix timestamp>
<nonce>
<SHA-256 of exact request body>
```

Redeemed sessions must match the environment and Core audience before storage.
Cookies bind native identity, Core audience, environment and game.

## Backups and rotation

`ENGINE_BACKUP_KEYS_JSON` maps key IDs to 32-byte hex AES keys.
`ENGINE_BACKUP_ACTIVE_KEY_ID` selects the write key. `ENGINE_BACKUP_KEY_HEX`
remains a legacy decrypt/write fallback named `legacy`. Secrets belong only in the
service secret store. They must not appear in logs, code, reports or frontend.

Every new encrypted manifest includes key ID, native deployment identity,
plaintext hash/size and snapshot time. Object names have a random suffix so two
backups in one second, including a key rotation, cannot overwrite one another.
Logs include object name, ciphertext SHA-256, plaintext SHA-256 and key ID only.
AES-GCM authenticates the manifest. This is not S3 Object Lock/WORM; bucket-side
immutability must be established separately and is not claimed here.

Rotation procedure:
1. Add the new independent 32-byte key to the ring while retaining all old IDs.
2. Change the active ID, deploy, and require a fresh remote-readback/restore proof.
3. Restore one old-key and one new-key snapshot to isolated fresh volumes.
4. Retain an old decrypt key until every snapshot encrypted under it has expired,
   plus a review margin, and a separate escrow/recovery drill has passed.
5. API signing-key rotation and staff/session-key rotation are separate procedures;
   do not casually replace an existing signing key and break pending rounds.

## Empty-volume restoration

Set these only for an explicitly planned replacement volume:

- `ENGINE_RESTORE_OBJECT_KEY`: exact `native/<game>/<object>.aesgcm` from verified logs.
- `ENGINE_RESTORE_CIPHERTEXT_SHA256`: exact encrypted-object SHA-256 from those logs.
- `ENGINE_RESTORE_CONFIRM_DEPLOYMENT_ID`: same immutable native service identity.
- Existing S3 bucket credentials and decrypt key ring for that environment.

Startup restores before opening the native database or creating Studio directories.
The replacement directory must be empty (filesystem `lost+found` is tolerated).
The downloader checks ciphertext hash, authenticates/decrypts AES-GCM, checks
manifest identity, SQLite integrity and the database's immutable identity, then
publishes the new DB without overwriting an existing file or WAL/SHM. It writes a
persistent restore marker. A restart skips the download only when marker, requested
object/hash and DB identity match. Existing unmarked DBs fail closed while restore
flags are present. After the recovery proof is saved, remove the restore flags.

The disposable tests delete every file in their temporary native volume, preserve
one settled and one ambiguous pending round, restore into an empty directory, and
verify browser-session continuity, immutable outcome, same idempotency reference,
and exactly one wallet debit/credit. They use an in-memory S3/central-wallet test
double; live infrastructure replacement RTO/RPO must be measured separately.

`AGENCY_STUDIO_SYNC=0` is required for this DB-only recovery profile. Mutable Studio
release/media files are not yet archived by this SQLite backup format. Repository
assets and bundled configs are recovered from the pinned Git commit. A deployment
using mutable Studio files cannot claim full-volume recovery from this profile.

## Retention policy

Implemented bounded profile: keep all snapshots for at least 7 days, the newest valid
snapshot for each of the last 7 UTC dates, 4 ISO weeks, and 12 calendar months,
and always the newest verified snapshot. Delete only objects in the exact native
prefix with a valid managed-object name. Never prune while newest backup is stale,
its readback/decryption/integrity fails, credentials are missing, or the inventory
cannot be paginated completely. A dry-run plan and execution receipt must be kept.
Set `ENGINE_BACKUP_RETENTION_ENABLED=true`; first use `ENGINE_BACKUP_RETENTION_MODE=dry-run`
and inspect the sanitized plan. Set mode `apply` to enforce after each fresh verified
backup. The default bound is five deletions per run (maximum ten), an inventory cap
of 4,096 objects and at most 32 authenticated snapshot checks. The newest two and
the currently configured restore object are always protected. Legacy object names
without a random suffix and unrelated keys are never deleted. Every required keeper
and candidate is decrypted, integrity checked and matched to this exact immutable
native identity before any deletion. A foreign/tampered/missing/stale proof aborts
pruning. Deletes require the downloaded object's ETag through `If-Match`; a store
that rejects this condition fails closed. No unconditional fallback is attempted.

`/health/backup` includes the sanitized retention receipt when enabled, including
mode, policy ID, verification status, eligible and deleted counts. Runtime logs
separately record plan/completion/failure. A successful zero-delete run proves the
policy is active but does not assert an expired live backup existed. Fixture tests
exercise bounded deletion, tampering, foreign identity, unknown key, incomplete
pagination and changed ETag cases. Keep decrypt keys for all retained snapshots.

Railway's current official S3 compatibility page explicitly lists bucket lifecycle,
object versioning and object locks as unsupported:
https://docs.railway.com/storage-buckets#s3-compatibility . Therefore this application
policy supplies retention scheduling but cannot supply WORM protection. Production
requirements needing storage immutability need a separate capable storage target.

## Security and math review

The approved game math/art hashes are unchanged, checked by read-only CI. CI no
longer unpacks stale source archives or commits generated source back to the branch.
New tests cover immutable identity, foreign environment rejection, real path
containment, v2 canonical signing, wrong redeemed identity, production quarantine,
key rotation and full disposable native DB-volume loss.

### UNO: production-blocking math finding

The current virtual-credit generator has an 80% win gate. Conditional winning
ranks have `(weight/1,000,000, payout multiplier)` of `(100,200)`, `(900,80)`,
`(4000,30)`, `(30000,10)`, `(965000,2)`. Therefore expected payout/stake is exactly:

`0.8 * (100*200 + 900*80 + 4000*30 + 30000*10 + 965000*2) / 1,000,000 = 1.9536`.

This is **195.36% expected return**, with a **95.36% expected operator loss per
stake** before external costs. Payout means total credited amount after the
separate stake debit. The virtual-credit entertainment design cannot be approved
unchanged for a real-value operator wallet. No payout table was silently retuned.
The owner and an independent math reviewer must select and certify a separate
versioned production math profile. `secrets.randbelow` and `secrets.choice` select
server-side outcomes; the paid rank is independently reclassified from the cards.

### Mahjong

Native tickets use fresh `secrets.token_hex(32)` seeds, persisted before wallet
requests. The locked engine expands each seed with Python `random.Random`
(Mersenne Twister); it is deterministic and explicitly not a cryptographic RNG.
A fresh hidden seed per complete committed round limits cross-round state reuse,
and the full round is fixed before reveal, but this is not RNG certification.
Production requires a reviewed, versioned cryptographic deterministic generator
and refreshed math validation for the exact active configuration, or an explicit
independent acceptance rationale. Existing native round verification checks the
complete deterministic transcript. The previous simulation RTP is not a certificate
for any changed config or Studio multiplier table.

### Skygate

The provider path injects independent `crypto.randomBytes(6)` streams into base and
jackpot math. It does not use the demo seed-compressed PRNG. Public native results
null seed/state fields, and the outcome is stored before reserve. This revision
corrects the result's RNG label to the actual `randomBytes(6)` implementation.
Native money converts integer/decimal strings to BigInt units and applies one
half-up payout rounding after the complete bonus; the source math itself uses
JavaScript numbers and still requires independent numerical/long-tail evaluation.

### Primary references

- Python 3.12 random: https://docs.python.org/3.12/library/random.html
- Python 3.12 secrets: https://docs.python.org/3.12/library/secrets.html
- Node 24 crypto: https://nodejs.org/docs/latest-v24.x/api/crypto.html

These document library properties, not a certificate for any game implementation.
Independent security review, statistical certification, real external operator
conformance and actual distinct-person go-live approval remain outside this code's
self-attestation. Production remains quarantined.


## Independent-player concurrency repair

A focused concurrent-client test first failed on all three preceding runtimes: one
player's delayed, real signed local HTTP wallet response prevented an unrelated
player from completing a native round within three seconds. UNO held SQLite's
write transaction across wallet HTTP, Mahjong held one global request lock, and
Skygate queued all players on one Promise chain.

The runtime now serializes each player separately. UNO commits the durable outcome
and requested phase in a short transaction before any callback; callbacks assert
no SQLite transaction remains open. Python recovery also takes the same player and
round/ticket locks in that order. Idle Python locks are weakly retained, avoiding
an unbounded player-lock registry. Skygate uses per-player Promise queues with
cleanup, per-token redemption queues and a guarded recovery pass sharing those
player queues. Each runtime remains one process/replica with its own durable volume.

The same local regression now completes the unrelated player's entire native
round while the delayed reserve and a concurrent duplicate for the slow player
remain blocked. After releasing the delay, both retries produce the same stored
outcome and each player has exactly one debit and one credit. Existing restart,
lost-response and complete-volume replacement tests remain mandatory. This proves
that the specific global bottleneck is removed; it does not substitute for the
separate deployed 500/1,000-session latency/soak qualification.
