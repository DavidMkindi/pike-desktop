# Connect Pike accounts to Neon on Vercel

Pike's account service already selects PostgreSQL whenever `DATABASE_URL` is set; otherwise it uses local SQLite. The PostgreSQL driver is declared in `requirements.txt`.

## Create/connect the database

1. **Rotate the Vercel token you posted in chat now.** Treat it as compromised: revoke it in Vercel Account Settings → Tokens and create a replacement only if needed. Don't paste the replacement into chat, source files, or commit it.
2. Open the Pike website project in Vercel (`website` in the linked project settings), then open **Storage → Create Database → Neon** (or the Marketplace Neon integration). Create a Neon database and connect it to this Vercel project. Use the integration's option to expose the pooled connection string as `DATABASE_URL` if offered. If it uses another variable name, set `DATABASE_URL` to Neon’s pooled PostgreSQL connection string in **Project → Settings → Environment Variables**.
3. Ensure `DATABASE_URL` is configured for Production and Preview (and Development if needed). Keep it secret; never use a `NEXT_PUBLIC_` prefix.
4. Redeploy the project so the new environment variable is available. On first request, Pike creates its account tables automatically. Check the site's `/healthz` and then test account registration/login.

For local development, copy the pooled Neon connection string to `website/.env` as `DATABASE_URL=...` and load it before starting Flask, or keep using SQLite locally. `.env` must remain untracked.

## Important limitations

This changes the website's account store only (users, sessions, devices, access tokens, usage/settings). The desktop conversation history in the repository's root `database.py` is a separate local SQLite database; this does not migrate or sync that history to Neon. Back up/export any existing account data before switching databases: a new Neon database starts empty.

The Vercel project is linked locally at `website/.vercel/project.json`, but Vercel CLI is not installed/logged in here, and the Neon connection string has not been supplied. Therefore no remote database or project settings were changed from this workspace. Complete the integration in Vercel's dashboard using the steps above; never share the connection string or token here.
