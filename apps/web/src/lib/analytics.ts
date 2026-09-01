/**
 * First-party, privacy-preserving client analytics tracker for SabiScore.
 *
 * Enforces strict typed event names, recursive client-side PII scrubbing,
 * batched asynchronous dispatch, and reliable flush on page exit.
 * Strict zero third-party scripts and zero sensitive credentials logged.
 */

export type AnalyticsEventName =
  | "match_viewed"
  | "prediction_inspected"
  | "share_card_generated"
  | "favorite_toggled"
  | "saved_match_toggled"
  | "key_created"
  | "key_revoked"
  | "notification_subscribed"
  | "notification_read"
  | "preferences_updated"
  | "dashboard_viewed"
  | "developer_hub_viewed"
  | "performance_viewed"
  | "filter_applied";

export interface AnalyticsEvent {
  event_id?: string;
  event_name: AnalyticsEventName;
  properties?: Record<string, unknown>;
  session_id?: string;
  anonymous_id?: string;
  client_platform?: string;
  timestamp?: string;
}

const SENSITIVE_KEY_PATTERNS = [
  "password",
  "token",
  "secret",
  "email",
  "auth",
  "key",
  "bearer",
  "credential",
  "cookie",
];

/**
 * Recursively scrub sensitive keys and patterns from event property payloads.
 */
export function scrubProperties(obj: unknown): unknown {
  if (obj === null || obj === undefined) return obj;
  if (typeof obj !== "object") return obj;

  if (Array.isArray(obj)) {
    return obj.map((item) => scrubProperties(item));
  }

  const cleaned: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
    const lowerKey = key.toLowerCase();
    const isSensitive = SENSITIVE_KEY_PATTERNS.some((pattern) =>
      lowerKey.includes(pattern)
    );
    if (isSensitive) {
      continue; // redact completely
    }

    if (typeof value === "string") {
      // Redact potential email addresses
      if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
        continue;
      }
      // Redact potential JWT tokens
      if (value.startsWith("eyJ") && value.length > 30) {
        continue;
      }
      cleaned[key] = value;
    } else if (typeof value === "object" && value !== null) {
      cleaned[key] = scrubProperties(value);
    } else {
      cleaned[key] = value;
    }
  }
  return cleaned;
}

class AnalyticsTracker {
  private queue: AnalyticsEvent[] = [];
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private maxBatchSize = 10;
  private flushIntervalMs = 3000;
  private sessionId = "";

  constructor() {
    if (typeof window !== "undefined") {
      this.sessionId = this.getOrCreateSessionId();
      this.setupLifecycleListeners();
    }
  }

  private getOrCreateSessionId(): string {
    try {
      let id = sessionStorage.getItem("sabi_session_temp_id");
      if (!id) {
        id = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `sess_${Date.now()}`;
        sessionStorage.setItem("sabi_session_temp_id", id);
      }
      return id;
    } catch {
      return `sess_${Date.now()}`;
    }
  }

  private setupLifecycleListeners(): void {
    if (typeof window === "undefined") return;

    window.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        this.flush();
      }
    });

    window.addEventListener("beforeunload", () => {
      this.flush();
    });
  }

  /**
   * Track an analytical event with optional properties.
   */
  public track(
    eventName: AnalyticsEventName,
    properties: Record<string, unknown> = {}
  ): void {
    try {
      const scrubbed = scrubProperties(properties) as Record<string, unknown>;
      const eventItem: AnalyticsEvent = {
        event_id: typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : undefined,
        event_name: eventName,
        properties: scrubbed,
        session_id: this.sessionId,
        client_platform: "web",
        timestamp: new Date().toISOString(),
      };

      this.queue.push(eventItem);

      if (this.queue.length >= this.maxBatchSize) {
        this.flush();
      } else if (!this.flushTimer) {
        this.flushTimer = setTimeout(() => {
          this.flushTimer = null;
          this.flush();
        }, this.flushIntervalMs);
      }
    } catch (err) {
      // Analytics must never throw or disrupt core application flow
      console.warn("Analytics track error:", err);
    }
  }

  /**
   * Flush all queued events to the backend ingestion endpoint.
   */
  public flush(): void {
    if (this.queue.length === 0) return;

    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }

    const batch = [...this.queue];
    this.queue = [];

    const payload = JSON.stringify({ events: batch });

    if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      const blob = new Blob([payload], { type: "application/json" });
      const sent = navigator.sendBeacon("/api/analytics/events", blob);
      if (sent) return;
    }

    if (typeof fetch !== "undefined") {
      fetch("/api/analytics/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
        keepalive: true,
      }).catch(() => {
        // Silent fail-safe
      });
    }
  }
}

export const analytics = new AnalyticsTracker();
