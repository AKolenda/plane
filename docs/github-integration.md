# GitHub integration

The Community Edition can link GitHub pull requests to work items, move those work items through states as the pull requests progress, and sync GitHub issues with Plane. It works with github.com and GitHub Enterprise Server. None of it depends on Commercial Edition code.

- [What it does](#what-it-does)
- [Choose how Plane talks to GitHub](#choose-how-plane-talks-to-github)
- [Option A: GitHub App (recommended)](#option-a-github-app-recommended)
- [Option B: OAuth App](#option-b-oauth-app)
- [Environment variables](#environment-variables)
- [GitHub Enterprise Server](#github-enterprise-server)
- [Run it locally with Docker Compose](#run-it-locally-with-docker-compose)
- [Configure a workspace](#configure-a-workspace)
- [How it behaves](#how-it-behaves)
- [Tests](#tests)

## What it does

| Feature             | How                                                                                                                                                                                                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Link a pull request | Put the work item ID in square brackets in the pull request title or description, e.g. `[ENG-123] Add retries`. Several references (`[ENG-1][WEB-7]`) link several work items, across projects of the same workspace. Bare IDs such as `ENG-123` are ignored, so version numbers and prose never link by accident. |
| Move work items     | Each project maps pull request events to states: draft opened, opened, review requested, ready for review, approved, merged, closed without merging. A mapping can be limited to a target branch, e.g. merged into `staging` → **In QA**, merged into `main` → **Deployed**. Globs such as `release/*` work.       |
| Pull request status | The work item page lists linked pull requests with their repository, number, title, target branch and state (open, draft, merged, closed).                                                                                                                                                                         |
| Issue sync          | Per watched repository: off, GitHub → Plane, or both ways. A GitHub issue labelled `plane` becomes a work item; with two-way sync a work item labelled `github` becomes a GitHub issue. Title, description and open/closed state stay in sync. Both labels are configurable.                                       |
| Settings            | Workspace settings → **GitHub**: connect accounts or organizations, choose repositories, configure issue sync. Project settings → **GitHub**: pull request state mapping.                                                                                                                                          |

## Choose how Plane talks to GitHub

You can enable either or both. Each workspace can then connect any number of accounts or organizations.

|                    | GitHub App                                                    | OAuth App                                                                    |
| ------------------ | ------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Connects           | An organization or user account where the app is installed    | The personal account that authorizes Plane                                   |
| Repositories       | The ones selected during installation                         | Any repository the user can administer                                       |
| Webhooks           | One app-level webhook, configured once                        | Plane creates one webhook per watched repository                             |
| Acts as            | The app's bot (`your-app[bot]`)                               | The user who connected                                                       |
| Credentials stored | App ID, private key, webhook secret in instance configuration | OAuth client in instance configuration; user token encrypted in the database |

## Option A: GitHub App (recommended)

Create the app under **Settings → Developer settings → GitHub Apps → New GitHub App** of the organization (or your account). Replace `https://plane.example.com` with your Plane URL (`WEB_URL`).

| Field                                                  | Value                                                                         |
| ------------------------------------------------------ | ----------------------------------------------------------------------------- |
| Homepage URL                                           | `https://plane.example.com`                                                   |
| Callback URL                                           | `https://plane.example.com/api/integrations/github/callback/`                 |
| Request user authorization (OAuth) during installation | **On**. Plane uses it to verify the installing user can see the installation. |
| Setup URL                                              | Leave empty (unused while the option above is on)                             |
| Redirect on update                                     | On                                                                            |
| Webhook → Active                                       | On                                                                            |
| Webhook URL                                            | `https://plane.example.com/api/integrations/github/webhook/`                  |
| Webhook secret                                         | A long random string, e.g. `openssl rand -hex 32`                             |

**Repository permissions**

| Permission    | Access                                                               |
| ------------- | -------------------------------------------------------------------- |
| Metadata      | Read-only (mandatory)                                                |
| Pull requests | Read-only                                                            |
| Issues        | Read and write (Read-only is enough if you only sync GitHub → Plane) |

No organization or account permissions are needed.

**Subscribe to events:** Pull request, Pull request review, Issues. (`installation` and `installation_repositories` are always delivered; Plane uses them to remove connections and repositories when the app is uninstalled or a repository is deselected.)

After saving, note the **App ID**, the app **slug** (the last part of `https://github.com/apps/<slug>`), the **Client ID**, generate a **client secret**, and generate a **private key** (`.pem`). Then set:

```bash
GITHUB_APP_ID=123456
GITHUB_APP_SLUG=plane-acme
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
GITHUB_APP_WEBHOOK_SECRET=the-webhook-secret
GITHUB_APP_CLIENT_ID=Iv23li...
GITHUB_APP_CLIENT_SECRET=...
```

`GITHUB_APP_PRIVATE_KEY` accepts the raw PEM, the PEM with `\n` escapes (handy in `.env` files), or the PEM base64-encoded on one line (`base64 -w0 key.pem`).

`GITHUB_APP_CLIENT_ID` and `GITHUB_APP_CLIENT_SECRET` are optional but strongly recommended. With them, Plane checks that the person connecting can actually access the installation. Without them, any workspace admin who knows an installation ID could claim it, as long as no other workspace has claimed it first.

## Option B: OAuth App

Create it under **Settings → Developer settings → OAuth Apps → New OAuth App**:

| Field                      | Value                                                         |
| -------------------------- | ------------------------------------------------------------- |
| Homepage URL               | `https://plane.example.com`                                   |
| Authorization callback URL | `https://plane.example.com/api/integrations/github/callback/` |

This must be a separate OAuth App from the one used for "Sign in with GitHub", because that one's callback URL is `/auth/github/callback/`.

Plane requests these **OAuth scopes**:

| Scope             | Why                                                                                                      |
| ----------------- | -------------------------------------------------------------------------------------------------------- |
| `repo`            | List repositories (including private ones), read pull requests, and read and write issues for issue sync |
| `admin:repo_hook` | Create and delete the webhook on each repository you watch                                               |

Watching a repository requires admin access to it, because that is what GitHub requires to create a webhook. Set:

```bash
GITHUB_INTEGRATION_OAUTH_CLIENT_ID=Ov23li...
GITHUB_INTEGRATION_OAUTH_CLIENT_SECRET=...
```

## Environment variables

All variables are read through Plane's instance configuration (`InstanceConfiguration`). `python manage.py configure_instance`, which runs when the API container starts, copies them from the environment into the database the first time it sees each key. Secrets are stored encrypted with `SECRET_KEY`. If a key's stored value is empty, Plane falls back to the environment variable, so you can add variables after the first start. To change a value that is already stored, update it as an instance admin with `PATCH /api/instances/configurations/` (`{"GITHUB_APP_ID": "123"}`), or set `SKIP_ENV_VAR=0` to read only from the environment.

| Variable                                 | Required for            | Encrypted | Description                                                                                |
| ---------------------------------------- | ----------------------- | --------- | ------------------------------------------------------------------------------------------ |
| `GITHUB_INTEGRATION_HOST_URL`            | GitHub Enterprise       | no        | Web URL of the GitHub host. Default `https://github.com`.                                  |
| `GITHUB_INTEGRATION_API_URL`             | rarely                  | no        | REST API base. Default `https://api.github.com` for github.com, `<host>/api/v3` otherwise. |
| `GITHUB_INTEGRATION_WEBHOOK_BASE_URL`    | local development       | no        | Public base URL GitHub delivers OAuth repository webhooks to. Default `WEB_URL`.           |
| `GITHUB_APP_ID`                          | GitHub App              | no        | App ID.                                                                                    |
| `GITHUB_APP_SLUG`                        | GitHub App              | no        | App slug, used for the installation URL.                                                   |
| `GITHUB_APP_PRIVATE_KEY`                 | GitHub App              | yes       | App private key (PEM, `\n`-escaped PEM, or base64).                                        |
| `GITHUB_APP_WEBHOOK_SECRET`              | GitHub App              | yes       | Webhook secret set on the app.                                                             |
| `GITHUB_APP_CLIENT_ID`                   | GitHub App, recommended | no        | App client ID, used to verify installations.                                               |
| `GITHUB_APP_CLIENT_SECRET`               | GitHub App, recommended | yes       | App client secret.                                                                         |
| `GITHUB_INTEGRATION_OAUTH_CLIENT_ID`     | OAuth App               | no        | OAuth App client ID.                                                                       |
| `GITHUB_INTEGRATION_OAUTH_CLIENT_SECRET` | OAuth App               | yes       | OAuth App client secret.                                                                   |

The integration is independent of `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`, which only power "Sign in with GitHub".

## GitHub Enterprise Server

1. Create the GitHub App or OAuth App on your GitHub Enterprise Server instance, exactly as above.
2. Set `GITHUB_INTEGRATION_HOST_URL=https://github.acme.com` (no trailing slash). The API URL defaults to `https://github.acme.com/api/v3`; set `GITHUB_INTEGRATION_API_URL` only if yours differs.
3. GitHub Enterprise Server must be able to reach Plane's webhook URL, and Plane's API and worker containers must be able to reach GitHub Enterprise Server.

Each connection remembers its host, so changing the host later does not break existing connections, but new connections use the new host.

## Run it locally with Docker Compose

1. Prepare the environment files:

   ```bash
   ./setup.sh
   ```

2. GitHub must be able to reach your machine. Open a tunnel to the API port, for example:

   ```bash
   cloudflared tunnel --url http://localhost:8000
   # or: ngrok http 8000
   ```

3. Create a GitHub App (or OAuth App) as described above, using the tunnel URL for the webhook URL and `http://localhost:8000/api/integrations/github/callback/` for the callback URL. The callback is a browser redirect, so `localhost` works there.

4. Add the variables to `apps/api/.env`:

   ```bash
   GITHUB_APP_ID=123456
   GITHUB_APP_SLUG=plane-local-you
   GITHUB_APP_PRIVATE_KEY=<base64 -w0 your-app.private-key.pem>
   GITHUB_APP_WEBHOOK_SECRET=<secret>
   GITHUB_APP_CLIENT_ID=<client id>
   GITHUB_APP_CLIENT_SECRET=<client secret>
   # OAuth repository webhooks are created with this base URL:
   GITHUB_INTEGRATION_WEBHOOK_BASE_URL=https://<your-tunnel-host>
   ```

5. Start the backend (database, Redis, RabbitMQ, MinIO, API, worker, beat worker, migrator):

   ```bash
   docker compose -f docker-compose-local.yml up -d --build
   ```

   The `migrator` service applies the `0123_github_integration` migration. Webhooks are processed by the `worker` service, so keep it running.

6. Start the web app and open `http://localhost:3000`:

   ```bash
   pnpm install
   pnpm dev
   ```

7. Go to **Workspace settings → GitHub**, click **Connect Organization** (GitHub App) or **Connect Personal Account** (OAuth App), and finish on GitHub.

If you change variables after the first start, restart the containers (`docker compose -f docker-compose-local.yml restart api worker`). See the note on stored values under [Environment variables](#environment-variables).

## Configure a workspace

1. **Workspace settings → GitHub → Connections.** Connect one or more organizations or accounts. Only workspace admins can do this, and an app installation belongs to a single workspace.
2. **Repository Mapping → Add repository.** Pick the repositories whose pull requests and issues Plane should watch. Pull request linking works as soon as a repository is watched; the project column is only needed for issue sync.
3. For issue sync, choose a **project** and a mode (**GitHub → Plane** or **Both ways**). Optionally change the labels (default `plane` on GitHub, `github` in Plane) and the states used for open and closed issues (defaults: the project's default state and its first completed state).
4. **Project settings → GitHub.** Add pull request state mappings: an event, an optional target branch, and the state to move to. Leave the branch empty to match every branch.

## How it behaves

**Linking.** Every pull request delivery re-reads the title and description, so editing them links or unlinks work items. References to unknown IDs, archived items, or other workspaces are ignored.

**State changes.** Each pull request event moves every linked work item that has a mapping for that event and target branch. A branch-specific mapping beats the catch-all one, an exact branch beats a glob, and a longer glob beats a shorter one. A work item linked later by an edit moves to the state for where the pull request already is (open, draft, merged or closed). Edits never move an already-linked work item, so manual changes stick. Changes are recorded in the work item's activity as the workspace's **GitHub** bot user, and trigger the usual notifications. Late, out-of-order deliveries (an older `updated_at` than one already applied) are ignored.

**Issue sync.**

- GitHub → Plane: a GitHub issue that is opened, labelled or edited while carrying the GitHub label is imported into the repository's project, with a link back to GitHub. After that, title, description (rendered from GitHub Markdown) and open/closed state follow GitHub.
- Plane → GitHub (both ways only): a work item carrying the Plane label in that project is created as a GitHub issue, with a link in Plane. After that, name, description and state follow Plane. Completed states close the issue as _completed_, cancelled states as _not planned_.
- Plane keeps a snapshot of both sides, so only fields that changed are written, and the webhook or activity echo of its own write is ignored.
- Comments, assignees, labels and milestones are not synced.

**Security.** Webhooks must carry a valid `X-Hub-Signature-256` HMAC; the app webhook uses `GITHUB_APP_WEBHOOK_SECRET`, and each OAuth repository webhook gets its own random secret. Deliveries are processed once per `X-GitHub-Delivery` ID. The connect flow carries a signed, 15-minute state bound to the user and workspace. OAuth tokens and webhook secrets are encrypted at rest.

**Disconnecting** deletes the repository webhooks Plane created (OAuth), the watched repositories, and their pull request links. Work items and their history stay. Uninstalling the GitHub App on GitHub does the same automatically.

## Tests

The backend tests cover reference parsing, link syncing, event classification, state-mapping resolution, the end-to-end webhook → state flow, issue sync in both directions, signature checks, and the settings API:

```bash
docker compose -f docker-compose-test.yml run --rm --build api-tests pytest plane/tests/unit/integrations
```
