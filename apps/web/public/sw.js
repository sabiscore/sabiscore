/**
 * SabiScore service worker — WEB_PUSH receiver only.
 *
 * Deliberately does NOT cache anything. A caching service worker on an
 * evidence-gated product is a liability: a stale cached analysis would show an
 * old verdict, old odds, or an old evidence state with no indication it is
 * stale, which is exactly the class of defect the platform's fail-closed rules
 * exist to prevent. This worker exists solely so the browser can deliver a
 * push message while the tab is closed.
 *
 * The payload is JSON produced by `backend/src/services/web_push_delivery.py`:
 *   { "title": string, "body": string, "url"?: string }
 */

self.addEventListener("install", () => {
  // Take over immediately so the first subscribe does not need a reload.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    // A malformed or unencrypted payload must not throw inside the worker —
    // an uncaught error here kills the notification entirely.
    payload = {};
  }

  const title = typeof payload.title === "string" && payload.title ? payload.title : "SabiScore";
  const body = typeof payload.body === "string" ? payload.body : "";
  // Only same-origin relative paths are honoured; an absolute URL from a
  // spoofed payload must never become a click-through target.
  const url = typeof payload.url === "string" && payload.url.startsWith("/") ? payload.url : "/";

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/icon.svg",
      badge: "/icon.svg",
      // Collapse repeats for the same fixture rather than stacking them.
      tag: url,
      data: { url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      // Focus an existing tab before opening a new one — a reader who already
      // has SabiScore open should not accumulate duplicate windows.
      for (const client of clientList) {
        if ("focus" in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
