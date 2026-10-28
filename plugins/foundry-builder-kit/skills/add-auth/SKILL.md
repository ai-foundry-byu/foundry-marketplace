---
name: add-auth
description: Add authentication (sign-in, sign-up, sign-out, protected routes) to a web project end to end. Audits the framework and existing auth, recommends a provider with the trade-off stated, implements it, and verifies with a real build. Use when the user says "add auth", "add sign-in", "add login", "users need to sign in", "protect this page", or "add authentication". Pass a provider name (clerk, supabase, better-auth, authjs) to skip the recommendation, or --dry-run to audit only.
---

# add-auth: add sign-in to a project, correctly, in one pass

Arguments (`$ARGUMENTS`):

- empty: audit, recommend, confirm, implement
- a provider name (`clerk`, `supabase`, `better-auth`, `authjs`): skip the recommendation
- `--dry-run`: audit and recommend only, change nothing

## Step 1: audit the project (read before you write)

Run these checks and report a short summary before changing anything.

1. **Framework and package manager.**
   - `package.json` dependencies: `next`, `react`, `express`, `fastify`, `hono`, `@remix-run/*`, `astro`, `@sveltejs/kit`
   - Python: `requirements.txt` / `pyproject.toml` for Django, FastAPI, Flask
   - Lockfile tells you the package manager: `package-lock.json` (npm), `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb` / `bun.lock`
   - Next.js: note the major version. Next.js 16 renamed `middleware.ts` to `proxy.ts`. Use whichever file name the installed version expects.
   - Next.js: `app/` or `src/app/` means App Router; `pages/` means Pages Router.
2. **Existing auth.** Search for `next-auth`, `@auth/core`, `@clerk/`, `@supabase/ssr`, `@supabase/auth-helpers`, `better-auth`, `lucia`, `firebase/auth`, `passport`, `jsonwebtoken`, and env names `AUTH_SECRET`, `NEXTAUTH_SECRET`, `CLERK_SECRET_KEY`, `SUPABASE_URL`. If auth exists, stop and ask: replace it, or extend it?
3. **Database.** `prisma`, `drizzle-orm`, `pg`, `postgres`, `mysql2`, `better-sqlite3`, `mongoose`, `@supabase/supabase-js`; files `prisma/schema.prisma`, `drizzle.config.*`, `supabase/`.
4. **Secrets hygiene.** Confirm `.env*` (except `.env.example`) is in `.gitignore` before you create any env file. If it is not, fix that first (see the `secrets-hygiene` skill).

```bash
# a quick audit you can paste
cat package.json 2>/dev/null | grep -E '"(next|react|express|fastify|hono|astro|@clerk/[a-z-]+|next-auth|better-auth|@supabase/[a-z-]+|prisma|drizzle-orm)"'
ls app src/app pages src/pages 2>/dev/null | head
grep -nE '^\.env' .gitignore || echo "WARNING: .env is not gitignored"
```

## Step 2: recommend a provider

```
Already on Supabase (DB or project)?
  yes -> Supabase Auth (auth and data in one place, row-level security uses the same user id)
  no  -> Already have a database and an ORM (Prisma, Drizzle, plain Postgres)?
           yes -> Better Auth (open source, TypeScript, stores users in YOUR database)
           no  -> Want the fastest possible working sign-in and do not mind a vendor?
                    yes -> Clerk (hosted UI, about 15 minutes to working sign-in)
                    no  -> Better Auth with SQLite for dev, Postgres for prod
                           (or Auth.js with Google OAuth and JWT sessions for a no-database app)
```

Present the recommendation with five lines: why it fits, time to implement, cost at the expected user count, what you get out of the box, and the main trade-off. Free-tier limits change; check the provider's pricing page before quoting a number, and say the date you checked.

Ask for confirmation before implementing, unless the user named a provider.

## Step 3: implement

Rules for every provider:

- Create `.env.local` with placeholders only (`REPLACE_ME`). Never paste a real key into a file the agent writes unless the user gave it in this session and asked for it.
- Create or update `.env.example` with the same variable names and empty values, so teammates know what to set.
- Generate secrets locally: `openssl rand -base64 32`.
- Default to **public by default, protect explicitly**: protect a route by listing it, so you never lock out the landing page by accident.
- Check the session on the server for anything that reads or writes data. Hiding a button in the UI is not authorization.

### Clerk (Next.js)

1. `npm install @clerk/nextjs`
2. `.env.local`: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_REPLACE_ME`, `CLERK_SECRET_KEY=sk_test_REPLACE_ME`
3. Wrap the root layout's `{children}` in `<ClerkProvider>`.
4. Create `middleware.ts` (or `proxy.ts` on Next.js 16+) with `clerkMiddleware()` and a `createRouteMatcher(['/dashboard(.*)'])` for the protected routes.
5. Add a header component with `<SignedIn>`, `<SignedOut>`, `<SignInButton>`, `<UserButton>` and mount it in the main layout.
6. Add a protected example page that reads `auth()` on the server and shows the user id.

### Supabase Auth (Next.js)

1. `npm install @supabase/supabase-js @supabase/ssr`
2. `.env.local`: `NEXT_PUBLIC_SUPABASE_URL=https://REPLACE_ME.supabase.co`, `NEXT_PUBLIC_SUPABASE_ANON_KEY=REPLACE_ME`. The anon key is public by design; the `service_role` key is NOT and must never get a `NEXT_PUBLIC_` prefix.
3. `lib/supabase/client.ts` (`createBrowserClient`) and `lib/supabase/server.ts` (`createServerClient` with the cookie adapter from the `@supabase/ssr` docs).
4. Middleware/proxy that refreshes the session on each request.
5. `app/login/page.tsx` (email + password and one OAuth button) and `app/auth/callback/route.ts` (exchanges the code for a session).
6. Server-side user read: `const { data: { user } } = await supabase.auth.getUser()`. Use `getUser()`, not `getSession()`, for authorization decisions on the server; it revalidates the token.
7. Turn on row-level security for every table that holds user data, with a policy like `using (auth.uid() = user_id)`.

### Better Auth (Next.js)

1. `npm install better-auth`
2. `lib/auth.ts` (server, `betterAuth({...})` with your database adapter and `emailAndPassword: { enabled: true }`) and `lib/auth-client.ts` (`createAuthClient()`).
3. Catch-all route `app/api/auth/[...all]/route.ts` using the Next.js handler from the docs.
4. `.env.local`: `BETTER_AUTH_SECRET=<openssl output>`, `BETTER_AUTH_URL=http://localhost:3000`
5. Schema: `npx @better-auth/cli generate` (Prisma or Drizzle), then run your migration. No ORM: use the SQLite adapter for dev.
6. Sign-in page using `authClient.signIn.email()` and `authClient.signIn.social()`, and a button using `useSession()`.
7. Middleware/proxy that redirects unauthenticated requests on protected paths.

### Auth.js (NextAuth v5, Next.js)

1. `npm install next-auth@beta`
2. `auth.ts` exporting `{ handlers, auth, signIn, signOut }` from `NextAuth({ providers: [Google] })`.
3. `app/api/auth/[...nextauth]/route.ts` re-exporting `handlers`.
4. `.env.local`: `AUTH_SECRET=<openssl output>`, `AUTH_GOOGLE_ID=REPLACE_ME`, `AUTH_GOOGLE_SECRET=REPLACE_ME`
5. Middleware/proxy exporting `auth` as the middleware.
6. JWT sessions need no database. Database sessions need an adapter.

### Other stacks

| Stack | Use |
|---|---|
| Express / Fastify | Passport or Better Auth's Node handler, sessions in Postgres (`connect-pg-simple`) |
| React SPA (no server) | Clerk React SDK or Supabase JS; never roll your own token storage in `localStorage` |
| Astro, SvelteKit | Better Auth adapter for that framework |
| Django | `django-allauth` |
| FastAPI | `fastapi-users`, or verify a hosted provider's JWT with its JWKS endpoint |

Follow the framework's own conventions for file layout; the steps above are the shape, not literal paths.

## Step 4: verify (do not report done before this passes)

1. `npm run build` (or the project's build) exits 0, with no type errors.
2. Start the dev server and check, by hand or with Playwright:
   - an anonymous request to a protected route redirects to sign-in (or returns 401 for an API route)
   - after signing in, the protected page renders and shows the user id
   - sign-out clears the session and the protected route redirects again
3. `git status` shows no `.env.local` staged; `git check-ignore .env.local` prints the path.
4. Session cookies are `HttpOnly`, `Secure` in production, and `SameSite=Lax` or stricter (browser devtools, Application tab).

## Step 5: report

- what was implemented, and the files created or modified
- the manual steps left: create the provider project, paste keys into `.env.local` and the hosting platform's env settings, register OAuth redirect URIs (`http://localhost:3000/...` for dev AND the production URL)
- the cost at the stated scale, with the date the pricing page was checked
- a link to the provider's docs for the next feature (roles, organizations, MFA)

Next step for launch: run the `scale-10k` skill.
