# S3 evidence storage activation

Status vocabulary: the template and storage code **EXIST** and mocked behavior is
**TESTED**. The bucket is not **DEPLOYED** or **VERIFIED** until the commands below
succeed in the operator's AWS and Render accounts. Keep the worker disabled until
then.

On 2026-08-14, the root and backend gitignored env files matched the configured
bucket, region, and standard regional endpoint; credential shape and cross-file
parity were checked without printing values. Both read-only `HeadBucket` and
`GetBucketLocation` returned HTTP 403. Treat this as an authorization/bucket-identity
block, not as bucket verification. The live Render environment was not readable from
the checkout; `render.yaml` is desired configuration only.

## Provision

The existing bucket is `sabiscore-artifacts-prod-uswest2`. Validate its current
controls before changing them. `infra/aws/evidence-storage.yaml` expresses the
required retained state and defaults to that name; because the bucket already
exists, import it into a CloudFormation stack or reconcile it in place rather than
attempting to create a second bucket. The target state enables versioning, blocks
public access, denies non-TLS requests, and uses SSE-S3 (`AES256`). Current and
non-current evidence transitions to Glacier Flexible Retrieval after 90 days;
nothing expires automatically. Incomplete multipart uploads are aborted after seven
days.

The `sabiscore-render-evidence-writer` identity can only get the bucket location
and put/get objects below `raw/`, `processed/`, and `manifests/`. It cannot list,
delete, administer, or change the bucket. Create its access key separately, place
the key ID and secret directly in Render secrets, and never print either value.

Configure the scraper service with:

```text
SABISCORE_ARTIFACT_BUCKET=sabiscore-artifacts-prod-uswest2
SABISCORE_S3_REGION=us-west-2
SABISCORE_S3_ENDPOINT=https://s3.us-west-2.amazonaws.com
SABISCORE_S3_FORCE_PATH_STYLE=false
SABISCORE_S3_SSE=AES256
AWS_ACCESS_KEY_ID=<Render secret>
AWS_SECRET_ACCESS_KEY=<Render secret>
SCRAPER_PRODUCTION_ENABLED=false
```

The explicit endpoint is the standard regional AWS endpoint, not a custom
S3-compatible host. The AWS SDK standard credential chain supplies credentials;
application code contains none.

## Verify before activation

From the credentialed Render worker shell, run `pnpm --filter
@sabiscore/scraper storage:probe`. A passing result reports `ok: true`, the fixed
`manifests/probes/immutable-storage-v1.json` key, its SHA-256, and
`conflict_verified: true`. The probe conditionally writes the same fixed content
twice, checks the stored checksum, and proves different content at that key fails
as an immutable conflict.

Then run one approved acquisition while the worker gate is still false by invoking
the bounded scraper command manually. Confirm its raw object and manifest with
`HeadObject`, validate the local manifest, and confirm database ingestion. Only
after all checks pass may the operator set `SCRAPER_PRODUCTION_ENABLED=true`.

## Degraded operation and rollback

S3 writes include `ChecksumSHA256` and content-hash metadata. A matching 412 is an
idempotent replay; a different hash is an integrity failure. Transient S3 failure
is logged with bounded non-secret fields while the already-written local artifact
remains available for ingestion/retry.

Rollback by setting `SCRAPER_PRODUCTION_ENABLED=false`, stopping the worker, and
deactivating or deleting only the writer's access key. Retain the bucket and all
archived evidence. Feature, settlement, report, and model-artifact storage planes
remain deferred until their producing workflows have canonical data to archive.
