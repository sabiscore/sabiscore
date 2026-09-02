/**
 * Browser-side WEB_PUSH enrolment.
 *
 * The VAPID public key is fetched from the backend rather than read from a
 * `NEXT_PUBLIC_*` build variable, so rotating it never requires a frontend
 * redeploy and the repo gains no new public credential-shaped env var.
 *
 * Every failure mode returns a named reason instead of throwing. A reader who
 * denies the permission prompt, or a deployment with the channel switched off,
 * must produce a specific message — not a generic "something went wrong", and
 * never a silent no-op that leaves the UI claiming push is on.
 */

export type WebPushEnableReason =
  | "enabled"
  | "unsupported"
  | "not_configured"
  | "permission_denied"
  | "registration_failed";

export interface WebPushEnableResult {
  enabled: boolean;
  reason: WebPushEnableReason;
}

/**
 * VAPID keys travel as base64url; `PushManager.subscribe` wants raw bytes.
 * Exported because this is the one piece of the flow that is pure and worth
 * pinning — a padding or alphabet mistake here produces an
 * `InvalidCharacterError` deep inside the browser with no useful message.
 */
export function urlBase64ToUint8Array(base64UrlKey: string) {
  const padding = "=".repeat((4 - (base64UrlKey.length % 4)) % 4);
  const base64 = (base64UrlKey + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  // Backed by an explicit ArrayBuffer, not the default ArrayBufferLike: since
  // TypeScript 5.7 `Uint8Array` is generic over its buffer, and the
  // SharedArrayBuffer arm is not assignable to `BufferSource`, so
  // `PushManager.subscribe` rejects the loosely-typed form.
  const output = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) {
    output[i] = raw.charCodeAt(i);
  }
  return output;
}

export function isWebPushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** Returns the key, or null when the deployment has WEB_PUSH switched off. */
export async function fetchVapidPublicKey(): Promise<string | null> {
  try {
    const response = await fetch("/api/notifications/push/public-key", { cache: "no-store" });
    if (!response.ok) return null;
    const data = (await response.json()) as { configured?: boolean; public_key?: string | null };
    return data.configured && data.public_key ? data.public_key : null;
  } catch {
    return null;
  }
}

/**
 * Register the service worker, obtain browser permission, subscribe, and
 * persist the endpoint server-side. Safe to call repeatedly — the browser
 * returns the existing subscription and the backend upserts on endpoint.
 */
export async function enableWebPush(): Promise<WebPushEnableResult> {
  if (!isWebPushSupported()) {
    return { enabled: false, reason: "unsupported" };
  }

  const publicKey = await fetchVapidPublicKey();
  if (!publicKey) {
    return { enabled: false, reason: "not_configured" };
  }

  // Ask before registering the worker: a reader who declines should not be
  // left with a service worker they never consented to.
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    return { enabled: false, reason: "permission_denied" };
  }

  try {
    const registration = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;

    const existing = await registration.pushManager.getSubscription();
    const subscription =
      existing ??
      (await registration.pushManager.subscribe({
        // Chrome refuses a subscription that is not userVisibleOnly; it also
        // matches what this worker actually does — every push shows a
        // notification, nothing runs silently in the background.
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      }));

    const response = await fetch("/api/notifications/push/devices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subscription.toJSON()),
    });
    if (!response.ok) {
      return { enabled: false, reason: "registration_failed" };
    }
    return { enabled: true, reason: "enabled" };
  } catch {
    return { enabled: false, reason: "registration_failed" };
  }
}

/** Unsubscribe locally and deactivate the stored device. Never throws. */
export async function disableWebPush(): Promise<void> {
  if (!isWebPushSupported()) return;
  try {
    const registration = await navigator.serviceWorker.getRegistration();
    const subscription = await registration?.pushManager.getSubscription();
    if (!subscription) return;
    // Tell the backend first: if the local unsubscribe succeeds but the request
    // fails, the server keeps pushing to an endpoint nothing is listening on.
    await fetch("/api/notifications/push/devices", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: subscription.endpoint }),
    });
    await subscription.unsubscribe();
  } catch {
    // Best effort — a failed cleanup must not surface as an app error.
  }
}

export const WEB_PUSH_FAILURE_COPY: Record<Exclude<WebPushEnableReason, "enabled">, string> = {
  unsupported: "This browser does not support push notifications.",
  not_configured: "Push notifications are not enabled on this deployment yet.",
  permission_denied: "Browser notifications are blocked. Enable them in site settings to use push.",
  registration_failed: "Could not register this browser for push notifications.",
};
