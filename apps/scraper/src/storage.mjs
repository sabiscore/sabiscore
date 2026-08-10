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

async function putS3Object({ key, content, contentType, metadata = {} }) {
  const bucket = process.env.SABISCORE_ARTIFACT_BUCKET;
  if (!bucket) return null;
  const { HeadObjectCommand, PutObjectCommand, S3Client } = await import("@aws-sdk/client-s3");
  const client = new S3Client({
    endpoint: process.env.SABISCORE_S3_ENDPOINT || undefined,
    region: process.env.SABISCORE_S3_REGION || "auto",
    forcePathStyle: process.env.SABISCORE_S3_FORCE_PATH_STYLE === "true",
  });
  try {
    await client.send(new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: content,
      ContentType: contentType,
      IfNoneMatch: "*",
      ServerSideEncryption: process.env.SABISCORE_S3_SSE || undefined,
      Metadata: Object.fromEntries(
        Object.entries(metadata).map(([name, value]) => [name, String(value)])
      ),
    }));
  } catch (error) {
    const status = error?.$metadata?.httpStatusCode;
    if (status !== 412) throw error;
    const existing = await client.send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
    if (existing.Metadata?.sha256 !== String(metadata.sha256)) {
      throw new Error("immutable_object_conflict");
    }
  }
  return `s3://${bucket}/${key}`;
}

async function writeImmutable(kind, name, content, metadata = {}) {
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
  const uri = await putS3Object({
    key: relativeKey,
    content,
    contentType,
    metadata: { sha256: hash, run_id: context.runId, source_id: context.sourceId },
  });
  return {
    file,
    uri: uri ?? file,
    object_key: relativeKey,
    hash,
    size_bytes: Buffer.byteLength(content),
    content_type: contentType,
  };
}

export async function writeJson(kind, name, payload, metadata = {}) {
  await ensureStorage();
  const content = `${JSON.stringify(payload, null, 2)}\n`;
  return writeImmutable("processed", `${kind}-${name}.json`, content, metadata);
}

export async function writeRaw(name, content, metadata = {}) {
  return writeImmutable("raw", name, content, metadata);
}

export async function writeManifest(run) {
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
  await putS3Object({
    key: `manifests/${manifest.source_id}/${runId}.manifest.json`,
    content,
    contentType: "application/json",
    metadata: { run_id: runId, source_id: manifest.source_id },
  });
  return file;
}

export async function readFixture(path) {
  return readFile(path, "utf8");
}
