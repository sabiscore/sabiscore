import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { basename, extname, join, parse } from "node:path";
import { manifestDir, processedDir, rawDir } from "./config.mjs";

export async function ensureStorage() {
  await mkdir(rawDir, { recursive: true });
  await mkdir(processedDir, { recursive: true });
  await mkdir(manifestDir, { recursive: true });
}

export function contentHash(content) {
  const bytes = Buffer.isBuffer(content) ? content : Buffer.from(String(content), "utf8");
  return createHash("sha256").update(bytes).digest("hex");
}

export function contentChecksum(content) {
  const bytes = Buffer.isBuffer(content) ? content : Buffer.from(String(content), "utf8");
  return createHash("sha256").update(bytes).digest("base64");
}

async function atomicWrite(file, content) {
  await ensureStorage();
  const tempFile = `${file}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tempFile, content, "utf8");
  await rename(tempFile, file);
  return file;
}

function artifactContext(metadata = {}) {
  return {
    sourceId: metadata.sourceId ?? "node-scraper",
    league: metadata.league ?? "global",
    season: metadata.season ?? "unknown",
    runId: metadata.runId ?? randomUUID(),
    acquiredAt: metadata.acquiredAt ?? new Date().toISOString(),
  };
}

function storageFailureCode(error) {
  if (error?.message === "immutable_object_conflict") return "immutable_object_conflict";
  const status = Number(error?.$metadata?.httpStatusCode ?? 0);
  if (status === 401 || status === 403) return "s3_authorization_failed";
  if (status === 408 || status === 429 || status >= 500) return "s3_temporarily_unavailable";
  return "s3_write_failed";
}

function reportStorageFailure(error, key) {
  // SDK exception messages can contain endpoints or credentials, so log only bounded fields.
  const storagePlane = ["raw", "processed", "manifests"].includes(String(key).split("/")[0])
    ? String(key).split("/")[0]
    : "unknown";
  console.warn(JSON.stringify({
    event: "s3_write_degraded",
    error_code: storageFailureCode(error),
    storage_plane: storagePlane,
    object_key_sha256: contentHash(String(key)),
    http_status: Number(error?.$metadata?.httpStatusCode ?? 0) || null,
  }));
}

function buildS3Client(S3Client) {
  return new S3Client({
    endpoint: process.env.SABISCORE_S3_ENDPOINT || undefined,
    region: process.env.SABISCORE_S3_REGION || "us-west-2",
    forcePathStyle: process.env.SABISCORE_S3_FORCE_PATH_STYLE === "true",
  });
}

export async function putS3Object(
  { key, content, contentType, metadata = {} },
  dependencies = {},
) {
  const bucket = process.env.SABISCORE_ARTIFACT_BUCKET;
  if (!bucket) return null;
  const s3 = dependencies.s3 ?? await import("@aws-sdk/client-s3");
  const { HeadObjectCommand, PutObjectCommand, S3Client } = s3;
  const client = dependencies.client ?? buildS3Client(S3Client);
  const sha256 = metadata.sha256 ?? contentHash(content);
  const checksum = contentChecksum(content);
  const objectMetadata = { ...metadata, sha256 };
  try {
    await client.send(new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: content,
      ContentType: contentType,
      IfNoneMatch: "*",
      ChecksumSHA256: checksum,
      ServerSideEncryption: process.env.SABISCORE_S3_SSE || "AES256",
      Metadata: Object.fromEntries(
        Object.entries(objectMetadata).map(([name, value]) => [name, String(value)])
      ),
    }));
  } catch (error) {
    const status = error?.$metadata?.httpStatusCode;
    if (status !== 412) throw error;
    const existing = await client.send(new HeadObjectCommand({
      Bucket: bucket,
      Key: key,
      ChecksumMode: "ENABLED",
    }));
    if (
      existing.Metadata?.sha256 !== String(sha256)
      || (existing.ChecksumSHA256 && existing.ChecksumSHA256 !== checksum)
    ) {
      throw new Error("immutable_object_conflict");
    }
  }
  return `s3://${bucket}/${key}`;
}

export async function writeImmutable(kind, name, content, metadata = {}, dependencies = {}) {
  await ensureStorage();
  const context = artifactContext(metadata);
  const hash = contentHash(content);
  const extension = extname(name) || (kind === "raw" ? ".bin" : ".json");
  const stem = parse(name).name.replace(/[^a-zA-Z0-9._-]+/g, "-");
  const timestamp = context.acquiredAt.replace(/[:.]/g, "-");
  const relativeKey = [
    kind,
    context.sourceId,
    context.league,
    context.season,
    context.runId,
    `${timestamp}-${stem}-${hash}${extension}`,
  ].join("/");
  const root = kind === "raw" ? rawDir : processedDir;
  const file = join(root, context.sourceId, context.league, context.season, context.runId, basename(relativeKey));
  await mkdir(join(root, context.sourceId, context.league, context.season, context.runId), { recursive: true });
  await atomicWrite(file, content);
  const contentType = kind === "raw" ? "text/csv" : "application/json";
  let uri = null;
  let remoteStorage = process.env.SABISCORE_ARTIFACT_BUCKET ? "available" : "not_configured";
  let storageError = null;
  try {
    uri = await (dependencies.putObject ?? putS3Object)({
      key: relativeKey,
      content,
      contentType,
      metadata: { sha256: hash, run_id: context.runId, source_id: context.sourceId },
    }, dependencies);
  } catch (error) {
    if (storageFailureCode(error) === "immutable_object_conflict") throw error;
    remoteStorage = "unavailable";
    storageError = storageFailureCode(error);
    reportStorageFailure(error, relativeKey);
  }
  return {
    file,
    uri: uri ?? file,
    object_key: relativeKey,
    hash,
    size_bytes: Buffer.byteLength(content),
    content_type: contentType,
    remote_storage: remoteStorage,
    storage_error: storageError,
  };
}

export async function writeJson(kind, name, payload, metadata = {}) {
  await ensureStorage();
  const content = `${JSON.stringify(payload, null, 2)}\n`;
  return writeImmutable("processed", `${kind}-${name}.json`, content, metadata);
}

export async function writeRaw(name, content, metadata = {}, dependencies = {}) {
  return writeImmutable("raw", name, content, metadata, dependencies);
}

export async function writeManifest(run, dependencies = {}) {
  await ensureStorage();
  const now = new Date().toISOString();
  const runId = run.run_id ?? randomUUID();
  const manifest = {
    manifest_version: "2.0",
    run_id: runId,
    source_id: run.source_id ?? "node-scraper",
    adapter_version: run.adapter_version ?? "1.0.0",
    schema_version: run.schema_version ?? "1.0.0",
    started_at: run.started_at ?? now,
    completed_at: run.completed_at ?? now,
    status: run.status ?? "SUCCESS",
    record_count: run.record_count ?? 0,
    raw_files: run.raw_files ?? [],
    processed_files: run.processed_files ?? [],
    payload_hashes: run.payload_hashes ?? {},
    source_timestamp: run.source_timestamp ?? null,
    oldest_record_timestamp: run.oldest_record_timestamp ?? null,
    freshness: run.freshness ?? "UNKNOWN",
    errors: run.errors ?? [],
    licence: run.licence ?? {},
    attribution: run.attribution ?? null,
    generated_at: now,
    zero_paid_api: true,
    command: run.command ?? null,
    source_policy: run.source_policy ?? null,
    ...run
  };
  const file = join(manifestDir, `${runId}-${basename(manifest.source_id)}.manifest.json`);
  const content = `${JSON.stringify(manifest, null, 2)}\n`;
  await atomicWrite(file, content);
  const key = `manifests/${manifest.source_id}/${runId}.manifest.json`;
  try {
    await (dependencies.putObject ?? putS3Object)({
      key,
      content,
      contentType: "application/json",
      metadata: {
        sha256: contentHash(content),
        run_id: runId,
        source_id: manifest.source_id,
      },
    }, dependencies);
  } catch (error) {
    if (storageFailureCode(error) === "immutable_object_conflict") throw error;
    reportStorageFailure(error, key);
  }
  return file;
}

export async function probeImmutableStorage(dependencies = {}) {
  const bucket = process.env.SABISCORE_ARTIFACT_BUCKET;
  if (!bucket) throw new Error("s3_bucket_not_configured");
  const s3 = dependencies.s3 ?? await import("@aws-sdk/client-s3");
  const client = dependencies.client ?? buildS3Client(s3.S3Client);
  const key = "manifests/probes/immutable-storage-v1.json";
  const content = `${JSON.stringify({ probe: "sabiscore-immutable-storage", version: 1 })}\n`;
  const hash = contentHash(content);
  const request = {
    key,
    content,
    contentType: "application/json",
    metadata: { sha256: hash, probe: "immutable-storage-v1" },
  };

  await putS3Object(request, { s3, client });
  await putS3Object(request, { s3, client });
  let conflictVerified = false;
  try {
    await putS3Object({ ...request, content: `${content}conflict` }, { s3, client });
  } catch (error) {
    conflictVerified = storageFailureCode(error) === "immutable_object_conflict";
  }
  if (!conflictVerified) throw new Error("s3_conflict_probe_failed");

  const head = await client.send(new s3.HeadObjectCommand({
    Bucket: bucket,
    Key: key,
    ChecksumMode: "ENABLED",
  }));
  if (
    head.Metadata?.sha256 !== hash
    || (head.ChecksumSHA256 && head.ChecksumSHA256 !== contentChecksum(content))
  ) {
    throw new Error("s3_checksum_probe_failed");
  }
  return { ok: true, bucket, object_key: key, sha256: hash, conflict_verified: true };
}

export async function readFixture(path) {
  return readFile(path, "utf8");
}
