# SabiScore Authentication — Production Setup

This release upgrades the browser authentication surface to support:

- Email/password registration and sign-in.
- Google OpenID Connect sign-in and registration.
- HttpOnly `sabi_session` authentication cookies.
- Anonymous-state merge after successful authentication.
- OAuth state, nonce, and PKCE protection.
- Server-side Google ID-token signature/audience/issuer/nonce validation.
- Google verified-email account linking by normalized email.
- Account avatar/name hydration from Google.

## 1. Database migration

Run the migration before deploying the new backend:

```bash
cd backend
alembic upgrade head
```

Migration `0014_social_auth_identities`:

- Makes `users.hashed_password` nullable for social-only accounts.
- Adds a unique `users.username` field.
- Adds `users.avatar_url`.
- Adds `users.email_verified`.
- Adds `user_identities` for provider/subject mappings.

## 2. Google Cloud OAuth client

Create a Google OAuth 2.0 **Web application** client.

Required redirect URI for local development:

```text
http://localhost:3000/api/auth/google/callback
```

Required production redirect URI:

```text
https://<production-web-domain>/api/auth/google/callback
```

Register every real production hostname separately. Do not use a wildcard for the OAuth client's exact redirect URI.

Use the same Google client ID in both the Next.js and FastAPI environments.

## 3. Next.js environment

Set these variables on the Vercel/web deployment:

```text
NEXT_PUBLIC_APP_URL=https://<production-web-domain>
NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=true
GOOGLE_OAUTH_CLIENT_ID=<google-client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<google-client-secret>
SABISCORE_BACKEND_URL=https://<production-api-domain>
```

`GOOGLE_OAUTH_CLIENT_SECRET` is server-only and must never use a `NEXT_PUBLIC_` prefix.

## 4. FastAPI environment

Set these variables on the backend deployment:

```text
GOOGLE_OAUTH_ENABLED=true
GOOGLE_OAUTH_CLIENT_ID=<same-google-client-id>
```

The backend does not need the Google client secret. It verifies the signed OIDC ID token against Google's published JWKS and validates the configured audience.

## 5. Google consent-screen scopes

SabiScore requests only:

- `openid`
- `email`
- `profile`

No Google API access token is stored or requested for downstream Google services.

## 6. Authentication flow

### Password

```text
Browser
  -> Next.js /api/auth/login
  -> FastAPI /api/v1/auth/login
  -> signed SabiScore JWT
  -> HttpOnly sabi_session cookie
```

### Google

```text
Browser
  -> Next.js /api/auth/google/start
  -> Google authorization
  -> Next.js /api/auth/google/callback
  -> Google authorization-code exchange
  -> FastAPI /api/v1/auth/oauth/google
  -> Google JWKS + OIDC validation
  -> signed SabiScore JWT
  -> HttpOnly sabi_session cookie
```

The Google authorization code, ID token, and SabiScore JWT never appear in the browser URL.

## 7. Security properties

- OAuth `state` is generated per authentication attempt and stored in an HttpOnly SameSite cookie.
- OIDC `nonce` is generated per authentication attempt and verified by the backend.
- PKCE S256 is used for the authorization-code exchange.
- Google ID-token signature is verified against Google's rotating JWKS.
- `iss`, `aud`, `azp`, `exp`, `iat`, `sub`, and `nonce` are validated.
- Only Google accounts with `email_verified=true` are accepted.
- SabiScore sessions remain HttpOnly and are not stored in localStorage.
- OAuth callback destinations are restricted to same-origin relative paths to prevent open redirects.
- Existing anonymous favorites/saved matches are merged after authentication.

## 8. Production verification checklist

- [ ] `alembic upgrade head` completed successfully.
- [ ] Google OAuth Web client created.
- [ ] Production callback URI registered exactly.
- [ ] `NEXT_PUBLIC_APP_URL` points to the canonical production hostname.
- [ ] `GOOGLE_OAUTH_CLIENT_ID` matches between web and backend.
- [ ] `GOOGLE_OAUTH_CLIENT_SECRET` exists only on the web/server deployment.
- [ ] `GOOGLE_OAUTH_ENABLED=true` on the backend.
- [ ] HTTPS is active on the production web domain.
- [ ] Email/password registration works.
- [ ] Existing password account can sign in with the same verified Google email.
- [ ] New Google account is created exactly once across repeated sign-ins.
- [ ] Anonymous saved state merges after password and Google authentication.
- [ ] Logout invalidates the browser session cookie.
- [ ] OAuth cancellation returns to the originating application route with a recoverable error.
- [ ] Invalid state/nonce/code cannot establish a session.

## 9. Troubleshooting a failed Google sign-in (added 2026-09-27)

Find where the flow stopped. Each stage leaves a different trace.

| What the visitor sees | Where it stopped | Fix |
| --- | --- | --- |
| Google's own page: `Error 400: redirect_uri_mismatch` | Google rejected the callback before any SabiScore code ran | Google Cloud Console → APIs & Services → Credentials → the OAuth 2.0 Client ID whose ID the start route sends → **Authorized redirect URIs** → add exactly `https://sabiscore.vercel.app/api/auth/google/callback` (https, no trailing slash, no path after `callback`). Save; it can take a few minutes. |
| SabiScore: "Google sign-in is not configured for this deployment yet." | Either the web has no client ID, or the backend rejected the token because its `GOOGLE_OAUTH_CLIENT_ID` differs from the web's | Render log line `google_oauth_rejected reason=Google token audience does not match GOOGLE_OAUTH_CLIENT_ID` means the second. Set Render's `GOOGLE_OAUTH_CLIENT_ID` to the web's value exactly: the same string as Vercel's `GOOGLE_OAUTH_CLIENT_ID` or `AUTH_GOOGLE_ID`, ending `.apps.googleusercontent.com`, no quotes. Redeploy the backend. |
| SabiScore: "Google sign-in could not be completed. Please try again." | Backend rejected the token for another reason | Read the Render line `google_oauth_rejected reason=…` (and Vercel's `google_oauth_backend_rejected`): nonce, expiry, unverified email, or Google's keys unreachable. |

Read the client ID the web actually sends without opening any dashboard: request
`https://sabiscore.vercel.app/api/auth/google/start` without following redirects and read `client_id`
in the `Location` header. Client IDs are public; the secret never appears there.

A Render log line reading `POST /api/v1/auth/oauth/google 401` proves the redirect URI is registered:
Google redirected back, and the code exchange (which also checks the redirect URI) succeeded.
