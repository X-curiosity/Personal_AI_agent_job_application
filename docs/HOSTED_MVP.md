# Hosted Co-Apply GPT MVP

## Status

This is an isolated hosted MVP scaffold, not a live service. The existing `ui.py` remains the local single-user application and continues to use `.job_assistant/assistant.sqlite`. The hosted app starts from `hosted_ui.py` and never constructs or reads those local stores.

The MVP provides passwordless email registration/sign-in (magic link or numeric OTP), private multi-CV upload, deterministic CV-to-job comparison, five-minute signed download links, confirmed CV deletion, private targets, a reviewable application queue, optional LinkedIn OpenID identity linking, and on-demand data export. A separately deployed Supabase Edge Function deletes accounts only after fresh OTP authentication. Public sign-up, LinkedIn linking, and account deletion are disabled by default and in the Render blueprint. The hosted service does not submit applications or read local workspace records. Rule-based application preparation is a separate local CLI/UI flow with deterministic fields and per-submission approval; no model is used.

## Data boundaries

- Supabase Auth owns credentials. Email confirmation must remain enabled and verified in project settings. Password recovery requires the Reset Password email template to display the one-time code using `{{ .Token }}`.
- The Streamlit app uses only the publishable/anon key and the signed-in user's access token. The account-deletion Edge Function needs a service-role secret only in Supabase's function secrets; never configure it in Render or the Streamlit app.
- `supabase/migrations/202610270001_hosted_mvp.sql` creates private tables, owner-scoped RLS, and the non-public `private-cvs` bucket. Auth signup is rejected unless the submitted notice version and URL match the operator-configured database values; an Auth trigger records an immutable server-timestamped receipt. Private table and storage policies require that receipt. Auth `user_metadata` is only the signup assertion, never the authoritative receipt.
- CV object paths begin with the authenticated user's UUID. Storage RLS independently checks this path and a security-definer active-account predicate on every operation, so an unexpired JWT for a deleted Auth user cannot recreate storage objects.
- CVs are capped at 10 MB each and restricted to PDF, DOCX, TXT, and Markdown. Data export includes saved rows and original CV files up to 50 MB total. When the user explicitly compares a CV, its text is extracted on demand inside the hosted Streamlit process using the same canonical skill vocabulary as the public job export. Only matched/missing public skill terms enter session state and optional application notes; original CVs and extracted text are not sent to a model or job board. Downloads use signed links that expire after five minutes. The app validates declared file type and DOCX decompression limits, not every file signature or malware; scanning remains a launch consideration.
- The public company catalogue is shared catalogue data. Saved company targets, CV metadata, and applications are account-private.
- The existing Vercel company map remains separate. This deployment does not export private profile/application data.

## Local setup

1. Create a dedicated Supabase project in a supported European region if available. Do not reuse a project containing unrelated Storage policies or user data.
2. Keep email confirmation enabled. Configure the Supabase site URL and redirect allowlist for the eventual Render URL.
3. Before deploying, inspect policies on `storage.objects`; remove any broad policy that could grant access to objects in `private-cvs` outside the authenticated user's folder. RLS policies are permissive by default and combine with OR.
4. Run the SQL migration in the Supabase SQL editor. It is safe to rerun for this initial schema/policies. After publishing the Privacy Notice, set `hosted_privacy_config` from the SQL editor to the same notice version and HTTPS URL used in Render, for example: `update public.hosted_privacy_config set notice_version = 'v1', notice_url = 'https://your-domain.example/privacy', updated_at = now() where singleton = true;`. Do not enable sign-ups while the DB and Render values differ.
5. Keep service-role credentials out of Render and the Streamlit process. Render receives only `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`.
6. Configure the Magic Link email template link as `{{ .SiteURL }}/?token_hash={{ .TokenHash }}&type=email` and also display `{{ .Token }}` for numeric-code sign-in; configure the Reauthentication template with `{{ .Token }}`. The token-hash callback is server-readable and does not depend on browser URL fragments. Set `HOSTED_PUBLIC_URL` and Supabase Auth Site URL to the exact HTTPS hosted app origin and allow that callback. LinkedIn uses PKCE identity linking; a random callback ID references a single-use, ten-minute server-side OAuth state row. The callback consumes that row once and reconstructs the verifier without relying on a Streamlit session surviving the external redirect. `HOSTED_JOBS_URL` may point to the public `data/jobs.json` snapshot. To enable LinkedIn, configure Supabase's official `linkedin_oidc` provider with your LinkedIn app's client credentials and approved redirect, then set `HOSTED_LINKEDIN_ENABLED=true`. This links basic identity to an existing account; it does not import job preferences or connections.
7. Deploy `supabase/functions/delete-account/` with `verify_jwt` enabled. Verify that the Edge Function has `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY` available; these are function-only secrets/variables, never Render variables. The function validates the JWT and independently requires a matching subject plus OTP authentication no more than ten minutes old, removes files under the account UUID prefix, then deletes the Auth account. The storage RLS active-account check denies already-issued JWTs after deletion. A cross-service failure can leave deletion incomplete and requires support follow-up.
8. Complete and publish `docs/PRIVACY_NOTICE_DRAFT.md` at an HTTPS URL. Replace every placeholder and obtain appropriate legal review; the draft is not publishable as-is.
9. Set `HOSTED_PRIVACY_NOTICE_URL` and `HOSTED_PRIVACY_NOTICE_VERSION` to the published notice and its version, matching `hosted_privacy_config`. Signup submits the version and displayed URL; a database trigger rejects missing or mismatched values and records the notice URL/version with a server timestamp in `privacy_notice_acceptances`. Authenticated users have read-only access to their own receipt; RLS requires a receipt before private workspace data or files can be accessed. The receipt is application evidence of the user's acknowledgment, not a tamper-proof legal consent ledger. Keep `HOSTED_SIGNUPS_ENABLED=false` and `HOSTED_ACCOUNT_DELETION_ENABLED=false` until recovery email, export, deletion, and two-account RLS/storage isolation pass with synthetic accounts. Enable deletion only after the Edge Function passes; enable sign-up only after the privacy notice is complete.
10. Install the app with `uv sync`, set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in the shell (never a service-role key), then run:

   ```bash
   SUPABASE_URL='https://<project>.supabase.co' \
   SUPABASE_PUBLISHABLE_KEY='<publishable-key>' \
   .venv/bin/python -m streamlit run src/tau_job_application/hosted_ui.py \
     --server.address 127.0.0.1 --server.port 8507
   ```

## Render

`render.yaml` defines a free Frankfurt web service with auto-deploy and public sign-up disabled to prevent unreviewed code or unverified accounts from going live. Render requires public binding on `0.0.0.0`; credentials are entered as service environment variables, not committed. Configure `HOSTED_SUPPORT_EMAIL` and the published Privacy Notice contact before enabling user-facing recovery. The free plan may sleep when idle and is suitable only for a preview, not a reliability guarantee.

Before any public launch, configure Supabase email delivery/confirmation and allow the eventual Render URL. Do not provision paid plans or custom domains without explicit approval. Verify recovery code delivery, export contents, account deletion, RLS isolation with two synthetic users, and file access against the real project. Never use a real CV as a substitute for cross-account tests. Keep sign-up and account deletion disabled until those checks pass.

## Known MVP limits

- Password reset depends on a configured Supabase recovery email template and real email delivery; these are not configured or verified yet.
- Account deletion is gated behind a separately deployed Edge Function and fresh email OTP authentication, independently checked in that function. Storage removal and Auth deletion cannot share a transaction; partial failures can require support cleanup.
- The privacy notice is only a placeholder draft; the operator/contact/regions/retention/legal-basis details must be completed and reviewed before public sign-up.
- No automated application submission. The `Applied` stage means the user explicitly confirms a completed submission.
- No automatic submissions, local-data migration, or generated application packet. Jobs come from the bounded public snapshot; CV matching is deterministic term coverage, not a hiring prediction.
- Existing local career workspaces and application history are not migrated.
- Streamlit session tokens are kept server-side in per-browser Streamlit session state, not persisted in browser local storage. A fresh session may require signing in again.
- Email delivery, abuse/rate limiting, backup and data-retention policies require production setup and review.
