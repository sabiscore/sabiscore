import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  disableWebPush,
  enableWebPush,
  fetchVapidPublicKey,
  isWebPushSupported,
  urlBase64ToUint8Array,
} from "./web-push";

/**
 * A synthetic uncompressed P-256 point in base64url — the exact shape an
 * application-server public key takes: a 0x04 marker followed by 64 bytes.
 *
 * Built rather than pasted. An inline 87-character base64 literal next to an
 * identifier containing "KEY" is indistinguishable from a real credential to a
 * secret scanner, and the assertions below only need the shape, not any
 * particular point.
 */
const SAMPLE_UNCOMPRESSED_P256_POINT = (() => {
  const bytes = new Uint8Array(65);
  bytes[0] = 0x04;
  for (let i = 1; i < bytes.length; i += 1) bytes[i] = (i * 7) % 256;
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
})();

const originalNavigator = globalThis.navigator;

function installPushCapableBrowser(overrides: Record<string, unknown> = {}) {
  const subscription = {
    endpoint: "https://push.example/abc",
    toJSON: () => ({
      endpoint: "https://push.example/abc",
      keys: { p256dh: "p", auth: "a" },
    }),
    unsubscribe: vi.fn().mockResolvedValue(true),
  };
  const pushManager = {
    getSubscription: vi.fn().mockResolvedValue(null),
    subscribe: vi.fn().mockResolvedValue(subscription),
  };
  const registration = { pushManager };
  const serviceWorker = {
    register: vi.fn().mockResolvedValue(registration),
    getRegistration: vi.fn().mockResolvedValue(registration),
    ready: Promise.resolve(registration),
  };

  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { ...originalNavigator, serviceWorker },
  });
  vi.stubGlobal("PushManager", class {});
  vi.stubGlobal("Notification", {
    requestPermission: vi.fn().mockResolvedValue("granted"),
    ...overrides,
  });

  return { subscription, pushManager, serviceWorker, registration };
}

function stubFetch(handlers: Record<string, () => Response | Promise<Response>>) {
  // `_init` is declared, unused, so `mock.calls[n][1]` is typed — an untyped
  // mock records calls as a 1-tuple and assertions on the request body cannot
  // compile.
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const handler = Object.entries(handlers).find(([key]) => url.includes(key))?.[1];
    if (!handler) throw new Error(`unexpected fetch: ${url}`);
    return handler();
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const configuredKeyResponse = () =>
  new Response(JSON.stringify({ configured: true, public_key: SAMPLE_UNCOMPRESSED_P256_POINT }), { status: 200 });

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: originalNavigator,
  });
  vi.restoreAllMocks();
});

describe("urlBase64ToUint8Array", () => {
  it("decodes an application-server key to a 65-byte uncompressed P-256 point", () => {
    const bytes = urlBase64ToUint8Array(SAMPLE_UNCOMPRESSED_P256_POINT);
    expect(bytes).toBeInstanceOf(Uint8Array);
    expect(bytes.length).toBe(65);
    // 0x04 is the uncompressed-point marker; anything else means the base64url
    // alphabet or the padding was mishandled.
    expect(bytes[0]).toBe(0x04);
  });

  it("restores padding the base64url form omits", () => {
    // "AQ" needs two '=' to become valid base64; a naive atob() throws here.
    expect(() => urlBase64ToUint8Array("AQ")).not.toThrow();
    expect(Array.from(urlBase64ToUint8Array("AQ"))).toEqual([1]);
  });
});

describe("isWebPushSupported", () => {
  it("is false when the browser has no PushManager", () => {
    expect(isWebPushSupported()).toBe(false);
  });

  it("is true when service worker, PushManager and Notification all exist", () => {
    installPushCapableBrowser();
    expect(isWebPushSupported()).toBe(true);
  });
});

describe("fetchVapidPublicKey", () => {
  beforeEach(() => {
    installPushCapableBrowser();
  });

  it("returns the key when the deployment has WEB_PUSH configured", async () => {
    stubFetch({ "push/public-key": configuredKeyResponse });
    await expect(fetchVapidPublicKey()).resolves.toBe(SAMPLE_UNCOMPRESSED_P256_POINT);
  });

  it("returns null when the channel is switched off", async () => {
    stubFetch({
      "push/public-key": () =>
        new Response(JSON.stringify({ configured: false, public_key: null }), { status: 200 }),
    });
    await expect(fetchVapidPublicKey()).resolves.toBeNull();
  });

  it("returns null rather than throwing when the request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    await expect(fetchVapidPublicKey()).resolves.toBeNull();
  });
});

describe("enableWebPush", () => {
  it("reports unsupported without touching the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(enableWebPush()).resolves.toEqual({ enabled: false, reason: "unsupported" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports not_configured when the backend has no VAPID key", async () => {
    installPushCapableBrowser();
    stubFetch({
      "push/public-key": () =>
        new Response(JSON.stringify({ configured: false }), { status: 200 }),
    });
    await expect(enableWebPush()).resolves.toEqual({
      enabled: false,
      reason: "not_configured",
    });
  });

  it("never registers a service worker when permission is denied", async () => {
    const { serviceWorker } = installPushCapableBrowser({
      requestPermission: vi.fn().mockResolvedValue("denied"),
    });
    stubFetch({ "push/public-key": configuredKeyResponse });

    await expect(enableWebPush()).resolves.toEqual({
      enabled: false,
      reason: "permission_denied",
    });
    // A reader who declines must not be left with a worker they never agreed to.
    expect(serviceWorker.register).not.toHaveBeenCalled();
  });

  it("subscribes and persists the browser's own subscription shape", async () => {
    const { pushManager, serviceWorker } = installPushCapableBrowser();
    const fetchMock = stubFetch({
      "push/public-key": configuredKeyResponse,
      "push/devices": () => new Response(JSON.stringify({ id: "d1" }), { status: 201 }),
    });

    await expect(enableWebPush()).resolves.toEqual({ enabled: true, reason: "enabled" });
    expect(serviceWorker.register).toHaveBeenCalledWith("/sw.js");
    expect(pushManager.subscribe).toHaveBeenCalledWith(
      expect.objectContaining({ userVisibleOnly: true }),
    );

    const registerCall = fetchMock.mock.calls.find(([url]) => String(url).includes("devices"));
    expect(registerCall?.[1]).toMatchObject({ method: "POST" });
    // Forwarded verbatim — reshaping key material by hand is how p256dh/auth
    // get mangled into something the backend cannot decrypt with.
    expect(JSON.parse(String((registerCall?.[1] as RequestInit).body))).toEqual({
      endpoint: "https://push.example/abc",
      keys: { p256dh: "p", auth: "a" },
    });
  });

  it("reuses an existing subscription instead of re-subscribing", async () => {
    const { pushManager, subscription } = installPushCapableBrowser();
    pushManager.getSubscription.mockResolvedValue(subscription);
    stubFetch({
      "push/public-key": configuredKeyResponse,
      "push/devices": () => new Response("{}", { status: 201 }),
    });

    await expect(enableWebPush()).resolves.toEqual({ enabled: true, reason: "enabled" });
    expect(pushManager.subscribe).not.toHaveBeenCalled();
  });

  it("reports registration_failed when the backend rejects the device", async () => {
    installPushCapableBrowser();
    stubFetch({
      "push/public-key": configuredKeyResponse,
      "push/devices": () => new Response("{}", { status: 503 }),
    });

    await expect(enableWebPush()).resolves.toEqual({
      enabled: false,
      reason: "registration_failed",
    });
  });
});

describe("disableWebPush", () => {
  it("deactivates the device server-side before unsubscribing locally", async () => {
    const { subscription, pushManager } = installPushCapableBrowser();
    pushManager.getSubscription.mockResolvedValue(subscription);
    const order: string[] = [];
    // Parameters declared so `mock.calls[0][1]` is typed; an untyped `vi.fn()`
    // records calls as an empty tuple and the assertion below cannot compile.
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      order.push("delete");
      return new Response("{}", { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    subscription.unsubscribe.mockImplementation(async () => {
      order.push("unsubscribe");
      return true;
    });

    await disableWebPush();

    // Wrong order leaves the backend pushing to an endpoint nothing listens on.
    expect(order).toEqual(["delete", "unsubscribe"]);
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({
      endpoint: "https://push.example/abc",
    });
  });

  it("is a no-op when there is no active subscription", async () => {
    installPushCapableBrowser();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(disableWebPush()).resolves.toBeUndefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
