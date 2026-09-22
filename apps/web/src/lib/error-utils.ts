/**
 * Error Utilities
 * Safe helpers for error message handling to prevent React child errors
 */

import * as Sentry from '@sentry/nextjs';
import { parseApiError } from './api';

/**
 * Ensures the value is a primitive string suitable for rendering in React
 * Prevents "objects are not valid as a React child" errors
 */
export function safeMessage(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  
  if (value === null || value === undefined) {
    return 'An error occurred';
  }
  
  // Handle Error objects
  if (value instanceof Error) {
    return value.message || 'An error occurred';
  }
  
  // Handle objects with message property
  if (typeof value === 'object' && value !== null && 'message' in value) {
    return safeMessage((value as { message: unknown }).message);
  }
  
  // Fallback: stringify complex objects
  try {
    return JSON.stringify(value);
  } catch {
    return 'An error occurred';
  }
}

/**
 * Parse any error into a stable string message
 * Combines parseApiError with safeMessage for complete safety
 */
export function safeErrorMessage(error: unknown): string {
  if (
    typeof error === 'string' ||
    typeof error === 'number' ||
    typeof error === 'boolean' ||
    error instanceof Error
  ) {
    return safeMessage(error);
  }

  try {
    const parsed = parseApiError(error);
    return safeMessage(parsed.message);
  } catch {
    return 'An unexpected error occurred';
  }
}

/**
 * Format error for user display with optional fallback
 */
export function formatError(error: unknown, fallback = 'Something went wrong'): string {
  const msg = safeErrorMessage(error);
  return msg || fallback;
}

/**
 * Log error with structured context for monitoring
 * Only logs in development mode or when explicitly enabled
 */
export function logError(
  error: unknown,
  context?: {
    component?: string;
    action?: string;
    userId?: string;
    metadata?: Record<string, unknown>;
  }
): void {
  const errorInfo = {
    message: safeErrorMessage(error),
    stack: error instanceof Error ? error.stack : undefined,
    timestamp: new Date().toISOString(),
    userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
    ...context,
  };

  // Only log in development or with explicit flag
  const isDev = process.env.NODE_ENV === 'development';
  const loggingEnabled = typeof window !== 'undefined' && 
    (window as typeof window & { __SABISCORE_DEBUG__?: boolean }).__SABISCORE_DEBUG__;

  if (isDev || loggingEnabled) {
    console.error('[SabiScore Error]', errorInfo);
  }

  const sentryError = error instanceof Error ? error : new Error(errorInfo.message);

  try {
    Sentry.captureException(sentryError, {
      tags: {
        component: context?.component,
        action: context?.action,
      },
      extra: errorInfo,
    });
  } catch {
    // Never throw from telemetry capture.
  }
}

/**
 * Performance tracking utility for measuring operation duration
 */
export function trackPerformance(label: string): () => void {
  const start = performance.now();
  return () => {
    const duration = performance.now() - start;
    const isDev = process.env.NODE_ENV === 'development';
    if (isDev && duration > 100) {
      console.warn(`[Performance] ${label} took ${duration.toFixed(2)}ms`);
    }
  };
}

/**
 * Create user-friendly error messages based on error type
 */
export function getUserFriendlyError(error: unknown): string {
  const msg = safeErrorMessage(error).toLowerCase();

  if (msg.includes('rate limit')) {
    return 'Too many requests. Please wait a moment and try again.';
  }
  if (msg.includes('network') || msg.includes('fetch failed')) {
    return 'Network error. Please check your connection and try again.';
  }
  if (msg.includes('timeout')) {
    return 'Request timed out. Please try again.';
  }
  if (msg.includes('not found') || msg.includes('404')) {
    return 'Requested resource not found.';
  }
  if (msg.includes('unauthorized') || msg.includes('401')) {
    return 'Authentication required. Please log in.';
  }
  if (msg.includes('forbidden') || msg.includes('403')) {
    return 'Access denied. You do not have permission.';
  }
  if (msg.includes('server') || msg.includes('500')) {
    return 'Server error. Our team has been notified.';
  }

  return safeErrorMessage(error);
}
