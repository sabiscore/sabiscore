import assert from "node:assert/strict";
import { rm } from "node:fs/promises";
import test from "node:test";
import {
  contentChecksum,
  contentHash,
  probeImmutableStorage,
  putS3Object,
  storageFailureReport,
  writeManifest,
  writeRaw,
} from "../src/storage.mjs";

class PutObjectCommand {
  constructor(input) { this.input = input; }
}

class HeadObjectCommand {
  constructor(input) { this.input = input; }
}

class S3Client {}

const fakeS3 = { HeadObjectCommand, PutObjectCommand, S3Client };

test("storage probe failures expose only bounded redacted fields", () => {
  const error = Object.assign(
    new Error("User arn:aws:iam::123456789012:user/private is not authorized"),
    {
      $metadata: {
        httpStatusCode: 403,
        requestId: "sensitive-request-id",
        extendedRequestId: "sensitive-extended-id",
      },
    },
  );

  const report = storageFailureReport(error);
  assert.deepEqual(report, {
    ok: false,
    error_code: "s3_authorization_failed",
    http_status: 403,
  });
  assert.equal(JSON.stringify(report).includes("arn:aws"), false);
  assert.equal(JSON.stringify(report).includes("request-id"), false);
});

class InMemoryS3Client {
  constructor() {
    this.objects = new Map();
  }

  async send(command) {
    if (command instanceof PutObjectCommand) {
      const current = this.objects.get(command.input.Key);
      if (current) {
        const error = new Error("precondition failed");
        error.$metadata = { httpStatusCode: 412 };
        throw error;
      }
      this.objects.set(command.input.Key, command.input);
      return {};
    }
    if (command instanceof HeadObjectCommand) {
      const current = this.objects.get(command.input.Key);
      if (!current) throw new Error("missing object");
      return {
        Metadata: current.Metadata,
        ChecksumSHA256: current.ChecksumSHA256,
      };
    }
    throw new Error("unsupported command");
  }
}

function withBucket(name, operation) {
  const previous = process.env.SABISCORE_ARTIFACT_BUCKET;
  process.env.SABISCORE_ARTIFACT_BUCKET = name;
  return Promise.resolve(operation()).finally(() => {
    if (previous === undefined) delete process.env.SABISCORE_ARTIFACT_BUCKET;
    else process.env.SABISCORE_ARTIFACT_BUCKET = previous;
  });
}

test("S3 writes carry SHA-256 checksum and same-hash 412 is idempotent", () => withBucket(
  "test-bucket",
  async () => {
    const client = new InMemoryS3Client();
    const content = "immutable evidence\n";
    const request = {
      key: "raw/test/object.csv",
      content,
      contentType: "text/csv",
      metadata: { sha256: contentHash(content) },
    };
    await putS3Object(request, { client, s3: fakeS3 });
    await putS3Object(request, { client, s3: fakeS3 });
    const object = client.objects.get(request.key);
    assert.equal(object.ChecksumSHA256, contentChecksum(content));
    assert.equal(object.Metadata.sha256, contentHash(content));
    assert.equal(object.ServerSideEncryption, "AES256");
  },
));

test("S3 412 with a different hash remains an immutable conflict", () => withBucket(
  "test-bucket",
  async () => {
    const client = new InMemoryS3Client();
    const base = {
      key: "processed/test/object.json",
      contentType: "application/json",
    };
    await putS3Object({ ...base, content: "one" }, { client, s3: fakeS3 });
    await assert.rejects(
      putS3Object({ ...base, content: "two" }, { client, s3: fakeS3 }),
      /immutable_object_conflict/,
    );
  },
));

test("S3 outage preserves the local raw artifact and redacts failure details", () => withBucket(
  "test-bucket",
  async () => {
    const warnings = [];
    const originalWarn = console.warn;
    console.warn = (value) => warnings.push(String(value));
    let result;
    try {
      result = await writeRaw(
        "outage.csv",
        "Date,HomeTeam,AwayTeam\n",
        {
          sourceId: "storage-outage-test",
          league: "EPL",
          season: "2026",
          runId: "fixed-run",
          acquiredAt: "2026-08-14T00:00:00.000Z",
        },
        { putObject: async () => { throw new Error("secret=https://user:pass@example.test"); } },
      );
    } finally {
      console.warn = originalWarn;
    }
    try {
      assert.equal(result.remote_storage, "unavailable");
      assert.equal(result.storage_error, "s3_write_failed");
      assert.equal(result.uri, result.file);
      assert.equal(warnings.some((line) => line.includes("user:pass")), false);
    } finally {
      await rm(result.file, { force: true });
    }
  },
));

test("manifest upload metadata carries the manifest content hash", async () => {
  let upload;
  const file = await writeManifest(
    { source_id: "storage-manifest-test", run_id: "fixed-run", status: "SUCCESS" },
    { putObject: async (request) => { upload = request; return "s3://test/manifest"; } },
  );
  try {
    assert.equal(upload.metadata.sha256, contentHash(upload.content));
  } finally {
    await rm(file, { force: true });
  }
});

test("fixed-context storage probe verifies deduplication, checksum, and conflict", () => withBucket(
  "test-bucket",
  async () => {
    const client = new InMemoryS3Client();
    const result = await probeImmutableStorage({ client, s3: fakeS3 });
    assert.equal(result.ok, true);
    assert.equal(result.conflict_verified, true);
    assert.equal(client.objects.size, 1);
  },
));
