---
name: scale-10k
description: Audit a web app for launch at 10,000+ users and fix what will break first. Covers the app's own process model and state (in-memory state, single process, slow endpoints, double-submit duplicates), auth provider cost, database and connection pooling, sessions, rate limiting and bot protection, transactional email, privacy compliance, and monitoring, then produces a scorecard, a cost projection, and an ordered fix list. Use when the user says "scale to 10k", "prepare for launch", "production-ready", "handle more users", "will this survive a launch", or "what breaks at scale". Pass an area (app, auth, database, sessions, rate-limiting, email, compliance, infra), --audit-only, or --cost-estimate to narrow it.
---

# scale-10k: take a hobby app to launch-ready

Arguments (`$ARGUMENTS`):

- empty: full audit, report, then fix with confirmation
- one area: `app`, `auth`, `database`, `sessions`, `rate-limiting`, `email`, `compliance`, `infra`
- `--audit-only`: report, change nothing
- `--cost-estimate`: only the monthly cost table

Rating scale used everywhere below: **READY**, **NEEDS WORK**, **CRITICAL** (will break or leak at scale).

## Step 1: audit (read-only)

Run the checks for each area. Cite the file and line for every finding so the user can verify it. Never skip 1h: the app's own code breaks at launch more often than any provider does, and the SaaS areas below cannot see it.

### 1a. Auth provider
- Detect the provider (same detection as the `add-auth` skill).
- Look up its pricing page TODAY and record: free MAU limit, price per MAU past it, and the date checked. Hosted auth providers differ by an order of magnitude at 10k MAU; some jump from free to an enterprise tier. Flag **CRITICAL** if the projected bill at 10k MAU exceeds the user's stated budget.
- OAuth providers configured? MFA available for admin accounts?

### 1b. Database
- SQLite file on a serverless host: **CRITICAL** (no concurrent writers, the file may not persist between invocations).
- Serverless functions (Vercel, Netlify, Cloudflare) talking to Postgres without a pooler: **CRITICAL**. Look for a pooler URL (Supabase pooler on port 6543, Neon `-pooler` host, PgBouncer) or a serverless driver.
- Free-tier database: record its storage, connection, and pause-on-idle limits.
- Indexes: users(email unique), sessions(user_id), sessions(expires_at), and every foreign key you filter on. In Prisma/Drizzle schemas, check for `@@index` / `index()` on those columns.
- N+1 queries in list pages (a query inside a loop or a `.map(async ...)`).

```bash
grep -rnE 'DATABASE_URL|pgbouncer|pooler|:6543' --include='*.ts' --include='*.js' --include='*.env.example' . 2>/dev/null | grep -v node_modules | head
grep -nE '@@index|@unique|index\(' prisma/schema.prisma src/**/schema.ts 2>/dev/null | head -30
```

### 1c. Sessions
- Tokens in `localStorage`: **CRITICAL** (readable by any XSS). Use HttpOnly cookies.
- Long-lived JWT with no refresh rotation: **NEEDS WORK** (aim for access tokens of 15 to 60 minutes and rotating refresh tokens).
- Database sessions with no cleanup of expired rows: **NEEDS WORK**.
- Cookie flags: `HttpOnly`, `Secure`, `SameSite=Lax` or stricter.

### 1d. Rate limiting and abuse
- Libraries: `@upstash/ratelimit`, `express-rate-limit`, `rate-limiter-flexible`, or platform rules (Cloudflare, Vercel Firewall).
- Sign-in, sign-up, password-reset, and any endpoint that calls a paid API (LLM, SMS, email) must be rate limited. Missing: **CRITICAL**. An unlimited endpoint that calls an LLM is a direct path to a surprise bill.
- Bot protection on sign-up (Cloudflare Turnstile, hCaptcha, reCAPTCHA).
- Account enumeration: sign-in and reset return the same message whether or not the email exists.

### 1e. Transactional email
- Provider present (Resend, Postmark, SendGrid, SES)? Missing: **NEEDS WORK** (needed for verification and password reset).
- SPF, DKIM, and DMARC set for the sending domain: `dig +short TXT <your-domain>` and `dig +short TXT _dmarc.<your-domain>`.
- Volume estimate: plan for 1 to 2 emails per user per month at 10k users.

### 1f. Privacy and compliance
- Data export for a user (GDPR Art. 20) and account deletion (Art. 17).
- Audit log of auth events (sign-in, sign-out, password change, role change, deletion).
- Privacy policy linked from sign-up; cookie consent if you serve the EU.
- If you handle student records, health data, or payments, name the regime (FERPA, HIPAA, PCI) and stop to ask before building; those are not a weekend fix.

### 1g. Infrastructure
- Hosting platform, and whether production env vars are set there (not only in `.env.local`).
- `.env*` gitignored (see `secrets-hygiene`).
- Error monitoring (Sentry or similar) and uptime monitoring on the main URL.
- Backups: does the database plan include point-in-time recovery, and has anyone restored from it once?

### 1h. App architecture and load
- **Process model and state.** State kept in memory (a module-level list or dict, an in-process cache or session store, `global` counters), or data written only to the local disk of a serverless or container host: **CRITICAL**. It is lost on every restart or deploy, and the app cannot run two instances (each would hold different data). Look for a store that is not a database, and for a single `node server.js` / `uvicorn` / `flask run` with no persistence behind it.
- **Measured latency, not guessed.** Start the app locally and fire about 50 concurrent requests at the main list endpoint and the main create endpoint; record p95. Over 1 s: **NEEDS WORK**; errors or timeouts under that load: **CRITICAL**. Name the slow cause (a synchronous LLM or HTTP call in the request, an N+1 query, no pagination).

  ```bash
  npx autocannon -c 50 -a 500 http://localhost:3000/api/items            # Node; prints latency percentiles
  hey -n 500 -c 50 http://localhost:3000/api/items                        # or: brew install hey
  ab -n 500 -c 50 http://localhost:3000/api/items                         # or: ApacheBench (Ubuntu: sudo apt install apache2-utils)
  ```
- **Double submit.** Every create endpoint (sign-up, order, post, payment) needs both halves: the button is disabled while the request is in flight, AND the server rejects a duplicate (an idempotency key, or a unique constraint on the natural key). Test it: send the same create twice at once and count rows. Two rows: **CRITICAL** for anything that charges money or sends email, **NEEDS WORK** otherwise.

  ```bash
  for i in 1 2; do curl -s -X POST http://localhost:3000/api/items -H 'Content-Type: application/json' -d '{"title":"dup-test"}' & done; wait
  ```

## Step 2: report

```
Area             Rating       Finding (file:line)
App architecture CRITICAL     items kept in a module-level list, lost on restart (server/store.js:3); POST /api/items p95 2.4 s
Auth provider    READY        Clerk, free to 10k MAU (pricing checked 2026-01-15)
Database         CRITICAL     Postgres direct URL from serverless, no pooler (lib/db.ts:4)
Sessions         NEEDS WORK   ...
Rate limiting    CRITICAL     /api/generate calls an LLM with no limit (app/api/generate/route.ts:12)
Email            ...
Compliance       ...
Infrastructure   ...
```

Cost table, broken down by auth + database + email + hosting + cache, each line with its source:

```
Users     Auth   DB    Email  Hosting  Cache  Total/mo
current
1,000
5,000
10,000
50,000
```

Priority list: CRITICAL first (security risk or will break), then NEEDS WORK before 1k users, then nice-to-haves before 10k. Ask for confirmation before changing code.

## Step 3: fixes (implement in priority order, one commit per fix)

**Rate limiting (Upstash example).** `npm install @upstash/ratelimit @upstash/redis`, then:

```ts
// lib/rate-limit.ts
import { Ratelimit } from "@upstash/ratelimit";
import { Redis } from "@upstash/redis";
export const ratelimit = new Ratelimit({
  redis: Redis.fromEnv(),               // UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN
  limiter: Ratelimit.slidingWindow(10, "60 s"),
});
// in a route: const { success } = await ratelimit.limit(`signin:${ip}`); if (!success) return new Response("Too many requests", { status: 429 });
```

**App state and duplicates.** Move in-memory state into the database (or Redis for caches and rate-limit counters) so any instance can serve any request. Move slow work (LLM calls, emails, exports) out of the request into a queue or background job and return quickly. For double submit: disable the submit button while the request is in flight, and on the server add a unique constraint or accept an `Idempotency-Key` header and return the first result for a repeat.

**Connection pooling.** Supabase: switch the server connection string to the pooler URL. Neon: use the `-pooler` host or `@neondatabase/serverless`. Self-hosted Postgres: put PgBouncer in front.

**Session hardening.** Move tokens to HttpOnly cookies, add CSRF protection for cookie-authenticated form posts, add refresh rotation, and schedule a daily `DELETE FROM sessions WHERE expires_at < now()` (see the `scheduled-agents` skill for how to schedule it, or use the platform's cron).

**Bot protection.** Add Turnstile to sign-up and sign-in forms and verify the token on the server. Env: `NEXT_PUBLIC_TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY`.

**Email.** `npm install resend`; templates for verification, reset, welcome, and security alert; set SPF/DKIM/DMARC before the first real send.

**Roles.** Start with a `role` column (`admin`, `member`) and a server-side `requireRole("admin")` helper. Move to role and permission tables only when you have more than three roles.

**Compliance.** `GET /api/me/export` returns the user's data as JSON. `DELETE /api/me` soft-deletes with a grace period, then hard-deletes sessions and personal fields. An `audit_log(id, user_id, action, metadata, ip, user_agent, created_at)` table with an index on `(user_id, created_at)`.

**Monitoring.** Error tracking plus alerts on a spike in failed sign-ins, a spike in sign-ups, and rate-limit hits.

## Step 4: verify

1. Build passes and existing tests pass.
2. Rate limit actually fires: `for i in $(seq 1 15); do curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:3000/api/<limited-route>; done` shows 429s after the limit.
3. Pooler in use: the production connection string host or port matches the pooler.
4. App architecture: data survives an app restart, the load test p95 is under 1 s, and two simultaneous identical creates make one row.
5. A deleted test account can no longer sign in, and its export endpoint returns 401.
6. Re-run Step 1 and show the before and after scorecard.

## Step 5: final report

Before/after scorecard, files changed, updated cost table, and a numbered list of manual steps (accounts to create, keys to paste into the hosting platform, DNS records, migrations to run). Link the OWASP Authentication Cheat Sheet and the host's serverless database guidance.
