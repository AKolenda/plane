# NovaPro additions to Plane Community Edition

This fork adds the following to Plane Community Edition, with no Commercial Edition code:

| Feature                                     | Summary                                                                                           |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| [GitHub integration](github-integration.md) | Pull request linking, state automation, issue sync, GitHub Enterprise Server                      |
| [Custom properties](#custom-properties)     | Per-project text, number, date, select and user fields on work items                              |
| [External import](#external-import-api)     | Create or update work items from other systems, deduplicated by `external_source` + `external_id` |
| [Transcript importer](#transcript-importer) | Watches a folder of call transcripts and imports their action items                               |
| [Digest API](#digest-api)                   | A person's open work, blocked work and recent imports, with links                                 |
| [Typed webhooks](#outbound-webhooks)        | `issue.created`, `issue.updated`, `issue.state_changed`, `issue.assigned`, signed                 |
| [Stable links](#stable-work-item-links)     | `/<workspace>/work-items/<id>` keeps working after a project identifier is renamed                |
| [Deployment](#deployment)                   | Compose file that runs the fork's own images, external services, backups, TrueNAS                 |

Reference sections: [API endpoints](#api-endpoint-reference) · [Environment variables](#environment-variable-reference) · [Setup checklist](#setup-checklist) · [Tests](#tests).

## Where the code lives

The additions are kept apart from upstream code so upstream merges stay easy.

| Path                                                                                 | Contents                                                                                      |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `apps/api/plane/novapro/`                                                            | Custom property logic, import, digest, webhook event types, links, and their views and routes |
| `apps/api/plane/integrations/github/`                                                | GitHub integration                                                                            |
| `apps/api/plane/db/models/custom_property.py`, `…/integration/github_integration.py` | New models (migrations `0123`, `0124`)                                                        |
| `apps/web/components/custom-properties/`, `apps/web/components/github-integration/`  | Web UI                                                                                        |
| `tools/transcript-importer/`                                                         | Standalone transcript importer (standard-library Python)                                      |
| `deployments/novapro/`                                                               | Compose files, `.env.example`, backup and restore scripts                                     |
| `.github/workflows/novapro-images.yml`                                               | Builds and publishes the fork's images                                                        |

Changes to upstream files are one-line hooks:

- URL includes: `app/urls/__init__.py`, `api/urls/__init__.py`
- Model registration: `db/models/__init__.py`
- The webhook payload's `event_type`: `bgtasks/webhook_task.py`
- The GitHub sync trigger: `bgtasks/issue_activities_task.py`
- Settings tabs, routes, and sidebar and list-layout mounts in the web app
- A redirect-loop fix in `apps/web/lib/wrappers/authentication-wrapper.tsx`

All public API endpoints below use Plane's API tokens: send `X-Api-Key: <token>`. Create a token under **Profile settings → Personal access tokens**. Requests are rate limited by `API_KEY_RATE_LIMIT`.

## Custom properties

Project admins define properties under **Project settings → Custom properties**. Each property has:

- **name**, shown in the UI;
- **key**, a stable slug used by the API (derived from the name, e.g. `story_points`);
- **type**, which cannot change after creation: `text`, `number`, `date`, `select` (with options) or `user` (a project member).

Values appear and can be edited:

- in the work item sidebar and the peek view;
- as chips in list and kanban rows (up to two, then `+N`);
- as editable columns in project spreadsheets.

Renaming a select option keeps its id, so existing values follow the rename. Deleting a property deletes its values.

**Value formats**

| Type   | Write                                          | Read (web API) | Read (public API)                 |
| ------ | ---------------------------------------------- | -------------- | --------------------------------- |
| text   | string, up to 10 000 characters                | string         | string                            |
| number | number or numeric string                       | number         | number                            |
| date   | `YYYY-MM-DD` (a timestamp's date part is used) | `YYYY-MM-DD`   | `YYYY-MM-DD`                      |
| select | option id or option label (case-insensitive)   | option id      | option label                      |
| user   | user id or email of an active project member   | user id        | `{"id", "email", "display_name"}` |

Writing `null` or `""` clears a value. A request with one invalid value writes nothing.

```bash
# Read and write by key with an API token
curl -H "X-Api-Key: $TOKEN" \
  https://plane.example.com/api/v1/workspaces/acme/projects/$PROJECT_ID/work-items/$ID/custom-properties/
curl -X PATCH -H "X-Api-Key: $TOKEN" -H "Content-Type: application/json" \
  -d '{"severity": "High", "story_points": 5, "reviewer": "dana@novapro.ca", "due_to_customer": null}' \
  https://plane.example.com/api/v1/workspaces/acme/projects/$PROJECT_ID/work-items/$ID/custom-properties/
```

## External import API

`POST /api/v1/workspaces/<slug>/work-items/import/` creates or updates one work item, identified by `external_source` + `external_id` within the workspace. These are Plane's existing `Issue` columns. Re-importing the same item updates it instead of creating a duplicate. Concurrent imports of the same item are serialized, so even simultaneous retries produce one work item.

| Field                    | Required | Description                                                                             |
| ------------------------ | -------- | --------------------------------------------------------------------------------------- |
| `project`                | yes      | Project identifier (`ENG`) or id. The token's user must be a member or admin.           |
| `external_source`        | yes      | e.g. `transcript`, `slack` (up to 255 characters)                                       |
| `external_id`            | yes      | Stable id in the source system (up to 255 characters)                                   |
| `title`                  | yes      | Up to 255 characters                                                                    |
| `description`            | no       | Plain text or light markdown (paragraphs, `- ` bullets), converted to the editor's HTML |
| `description_html`       | no       | HTML instead of `description`; sanitized like the web editor's input                    |
| `source_url`             | no       | http(s) link added to the work item's Links once                                        |
| `labels`                 | no       | Label names (up to 20), matched case-insensitively, created when missing                |
| `assignee` / `assignees` | no       | Email or user id (or a list); each must be a project member                             |
| `custom_properties`      | no       | `{"<key>": value}`, as in [custom properties](#custom-properties)                       |

On re-import:

- the title and description are refreshed from the source;
- labels and assignees are only **added**, never removed, so changes made in Plane stay;
- the work item stays in the project it was created in.

The response is `201` when the work item was created and `200` when it was updated:

```json
{
  "id": "c5c739ac-0fe1-4744-b56e-112a230f05ab",
  "identifier": "ENG-5",
  "project_id": "cb8341c5-ab6f-4507-b52d-a872a1434147",
  "external_source": "slack",
  "external_id": "C123/1728450000.0001",
  "created": true,
  "url": "https://plane.example.com/acme/work-items/c5c739ac-0fe1-4744-b56e-112a230f05ab"
}
```

Send a JSON **list** of up to 100 items to import a batch. The response is `207` with one result per item, in order; rejected items read `{"error": "..."}`. Single-item validation errors return `400` with `{"error": "..."}`. Imports write work item activity and fire outbound webhooks like edits in the web app.

```bash
curl -X POST -H "X-Api-Key: $TOKEN" -H "Content-Type: application/json" \
  https://plane.example.com/api/v1/workspaces/acme/work-items/import/ -d '{
    "project": "ENG", "external_source": "slack", "external_id": "C123/1728450000.0001",
    "title": "Investigate flaky deploy", "description": "Reported in #dev.\n\n- check runner logs",
    "source_url": "https://novapro.slack.com/archives/C123/p1728450000000100",
    "labels": ["slack", "bug"], "assignee": "dana@novapro.ca"}'
```

## Transcript importer

`tools/transcript-importer` watches a folder (the TrueNAS share) for call transcripts: `.txt`, `.md`, `.vtt`, `.srt` and `.json`. It extracts action items and posts them to the import endpoint with `external_source="transcript"`.

- **Extraction:** explicit markers (`Action item:`, `TODO:`, `- [ ]`, …) and `Action items` / `Next steps` sections, with owners mapped to emails. An optional OpenAI-compatible LLM is used when a transcript has no markers.
- **Edits:** an edited transcript updates its existing work items rather than duplicating them.
- **Running it:** enable it in the Compose deployment with `TRANSCRIPT_IMPORTER_REPLICAS=1`.

Its [README](../tools/transcript-importer/README.md) lists the formats, owner syntax and every variable.

## Digest API

`GET /api/v1/workspaces/<slug>/digest/` returns what a person should look at. It feeds the desktop notification app and the morning digest. It only looks at projects that person is a member of.

| Parameter       | Default          | Description                                                                              |
| --------------- | ---------------- | ---------------------------------------------------------------------------------------- |
| `user`          | the token's user | Email or id. Reading someone else's digest needs a workspace admin token.                |
| `since`         | 24 hours ago     | ISO 8601 timestamp with a timezone (`2026-10-08T07:00:00Z`) for the `imported` list      |
| `blocked_label` | `blocked`        | Label name, case-insensitive                                                             |
| `blocked_scope` | `projects`       | `projects`: every open blocked work item in the user's projects; `assigned`: only theirs |
| `sources`       | all              | Comma-separated `external_source` values for `imported`, e.g. `transcript,slack`         |
| `limit`         | 50               | Items per list, 1–200; `counts` always has the full totals                               |

```json
{
  "user": { "id": "…", "email": "dana@novapro.ca", "display_name": "dana" },
  "workspace": "acme",
  "generated_at": "2026-10-09T07:00:00+00:00",
  "since": "2026-10-08T07:00:00+00:00",
  "counts": { "assigned_open": 2, "blocked": 1, "imported": 6 },
  "assigned_open": [
    {
      "id": "…",
      "identifier": "ENG-6",
      "name": "send the revised quote to Acme by Friday",
      "project": { "id": "…", "identifier": "ENG", "name": "Engineering" },
      "state": { "name": "Backlog", "group": "backlog" },
      "priority": "high",
      "target_date": null,
      "external_source": "transcript",
      "created_at": "…",
      "updated_at": "…",
      "url": "https://plane.example.com/acme/work-items/…"
    }
  ],
  "blocked": [],
  "imported": []
}
```

- **`assigned_open`:** open work items (not in a completed or cancelled state) assigned to the user, by priority, then due date.
- **`blocked`:** open work items carrying the blocked label, most recently updated first.
- **`imported`:** work items created by an import since `since`, newest first.

## Outbound webhooks

**What Community Edition already had.** Upstream CE delivers per-workspace webhooks:

- **Setup:** **Workspace settings → Webhooks**, by a workspace admin.
- **Events:** project, work item, cycle, module, and comment events.
- **Signing:** each delivery is signed with the webhook's secret key.
- **Retries:** up to 5 times with exponential backoff; a webhook that keeps failing is deactivated and its owner is emailed.
- **Logs:** deliveries are logged.
- **Gap:** work item updates arrive as `action: "updated"`, one delivery per changed field. The field name is in `activity.field` and differs between the web app (`state_id`, `assignee_ids`) and the public API (`state`, `assignees`).

**What this fork adds.** Every delivery's signed JSON body and headers now carry a specific type:

| `event_type` (body) / `X-Plane-Event-Type` (header) | When                                                                        | `changes`                                            |
| --------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------- |
| `issue.created`                                     | A work item is created (web, public API, import, GitHub sync)               | —                                                    |
| `issue.state_changed`                               | Its state changes, including changes made by GitHub pull request automation | `{"from": "<state id>", "to": "<state id>"}`         |
| `issue.assigned`                                    | Its assignees change                                                        | `{"added": ["<user id>"], "removed": ["<user id>"]}` |
| `issue.updated`                                     | Any other field changes                                                     | —                                                    |
| `<event>.<action>`                                  | Other events, e.g. `project.created`, `issue_comment.updated`               | —                                                    |

Existing fields (`event`, `action`, `data`, `activity`, …) are unchanged, so existing receivers keep working. `data` is the full work item, including its current state and assignees.

**Verify a delivery.** `X-Plane-Signature` is the hex HMAC-SHA256 of the raw request body, keyed with the webhook's secret key (shown when the webhook is created, or after **Regenerate**). Other headers: `X-Plane-Event` (`issue`, …) and `X-Plane-Delivery` (a new id for every attempt, including retries, so deduplicate on `data.id`, `event_type` and the work item's `updated_at` if you need to).

```python
import hashlib, hmac

def is_from_plane(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

```js
import crypto from "node:crypto";
const isFromPlane = (rawBody, signature, secret) =>
  crypto.timingSafeEqual(
    Buffer.from(crypto.createHmac("sha256", secret).update(rawBody).digest("hex")),
    Buffer.from(signature)
  );
```

**Receivers on your network.** Webhooks to private addresses are blocked to prevent server-side request forgery. To deliver to an internal service, for example the notification app at `notifier:9000` on the same Docker network, add it to `WEBHOOK_ALLOWED_HOSTS` (hostnames) or `WEBHOOK_ALLOWED_IPS` (IPs or CIDRs).

## Stable work item links

`<WEB_URL>/<workspace>/work-items/<work item id>` opens a work item directly. It looks the work item up by id when opened and redirects to its page, either `/<workspace>/browse/<IDENTIFIER>-<n>` or the archive page for archived items. It therefore keeps working after a project's identifier is renamed, which would break `/browse/ENG-123` links.

Signed-out users are sent to the login page and land on the work item after signing in. People who are not members of the project see "work item not found"; the link reveals nothing about it.

The import response, the digest and its consumers all use this form; build it as `${WEB_URL}/${slug}/work-items/${id}` (webhooks carry the id in `data.id`).

The lookup behind it is `GET /api/workspaces/<slug>/work-items/<id>/locate/` (session authenticated).

## Deployment

`deployments/novapro/` runs the fork's images (`ghcr.io/akolenda/plane-*`), never upstream's:

| File                       | Purpose                                                                                                                                                                                |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docker-compose.yml`       | The stack: web, space, admin, live, api, worker, beat-worker, migrator, Caddy proxy, transcript importer, scheduled database backups, and bundled Postgres, Valkey, RabbitMQ and MinIO |
| `docker-compose.build.yml` | Override that builds every image from the checkout instead of pulling                                                                                                                  |
| `.env.example`             | Every setting, documented; copy to `.env`                                                                                                                                              |
| `backup.sh` / `restore.sh` | `pg_dump` backups with verification and retention, and restore                                                                                                                         |

**Images.** `.github/workflows/novapro-images.yml` builds all seven images on every push to `preview` (or on demand) and pushes `:latest` and `:sha-<commit>` tags to GitHub Container Registry. Set it up once:

1. In the fork, enable Actions (**Actions** tab → enable workflows). Forks start with them off.
2. Run **NovaPro images** (Actions → NovaPro images → Run workflow), or push to `preview`.
3. Either make the packages public (GitHub → your profile → **Packages** → each `plane-*` package → **Package settings** → **Change visibility**), or log the host in once: `docker login ghcr.io -u <github user>` with a personal access token that has `read:packages`.

To build on the host instead, run this from a checkout:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

The web frontend build needs several GB of RAM. Build from a Linux checkout (CI, TrueNAS, WSL), or from the Git URL with `docker build https://github.com/AKolenda/plane.git#preview -f apps/web/Dockerfile.web`. `packages/i18n/locales` is a symlink, and a Windows checkout without `core.symlinks` turns it into a plain file, which produces frontends that show translation keys instead of text. The images have no host names baked in; the frontends call the API on the same origin through the proxy, so one build serves any address.

**Ports.** The proxy publishes `PLANE_HTTP_PORT` (default `8080`) and `PLANE_HTTPS_PORT` (default `8443`), never 80/443. `SITE_ADDRESS=:80` serves plain HTTP; put your existing reverse proxy or TLS terminator in front, or use Caddy's automatic HTTPS with `SITE_ADDRESS=plane.example.com` and a DNS challenge provider (`CERT_ACME_DNS`), because HTTP challenges need public port 80. Set `WEB_URL` to the address people use, including the port: `http://truenas.local:8080`.

**External services.** Each bundled service turns off with its `PLANE_BUNDLED_*_REPLICAS=0`:

| Service        | Turn off                           | Then set                                                                                                               |
| -------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Postgres       | `PLANE_BUNDLED_DB_REPLICAS=0`      | `DATABASE_URL=postgresql://user:pass@host:5432/plane` and `PGHOST=host`                                                |
| Valkey / Redis | `PLANE_BUNDLED_REDIS_REPLICAS=0`   | `REDIS_URL=redis://host:6379/` and `REDIS_HOST=host`                                                                   |
| RabbitMQ       | `PLANE_BUNDLED_MQ_REPLICAS=0`      | `AMQP_URL=amqp://user:pass@host:5672/vhost`                                                                            |
| Object storage | `PLANE_BUNDLED_STORAGE_REPLICAS=0` | `USE_MINIO=0`, `AWS_S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME`, `AWS_REGION` |

The bucket must exist, and browsers must be able to reach `AWS_S3_ENDPOINT_URL`, because uploads use pre-signed URLs. An external Postgres should be version 15 or newer; the backup container's `pg_dump` is 15.7, so for a newer server set the `db-backup` image to a matching `postgres:<version>-alpine`.

**Backups.** The `db-backup` service runs `backup.sh --loop`:

- **What it does:** a `pg_dump` (custom format) of `DATABASE_URL` every `BACKUP_INTERVAL_HOURS` into `PLANE_BACKUP_DIR`, then `pg_restore --list` to check the dump is readable.
- **Retention:** dumps older than `BACKUP_RETENTION_DAYS` are deleted.
- **Scope:** it works the same for bundled and external databases.

Uploaded files live in object storage; back up that volume or bucket separately. For example, use TrueNAS snapshots of the dataset given as `PLANE_UPLOADS`.

```bash
# Back up now
docker compose run --rm --entrypoint /bin/sh db-backup /scripts/backup.sh
# Restore (stop the app first)
docker compose stop api worker beat-worker live
docker compose run --rm --entrypoint /bin/sh db-backup /scripts/restore.sh /backups/plane-20261009-070000.dump
docker compose up -d
```

`backup.sh` also runs on any host with `pg_dump` (`DATABASE_URL=… BACKUP_DIR=… ./backup.sh`), so a TrueNAS cron job can call it instead.

**Upgrade.**

1. Push to `preview`, or run the workflow; images are tagged `latest`.
2. On the host, run `docker compose pull && docker compose up -d`. The `migrator` service applies database migrations before the API starts.
3. To pin a version, set `PLANE_IMAGE_TAG=sha-<commit>`.

### TrueNAS SCALE: Install via YAML

TrueNAS 24.10 (Electric Eel) and later run Docker Compose apps. Its **Install via YAML** dialog takes a Compose file but no `.env` file, so the file you paste only `include`s the deployment from a dataset.

1. **Create a dataset** for Plane, e.g. `tank/apps/plane` (mounted at `/mnt/tank/apps/plane`). Optionally create child datasets for `pgdata`, `uploads`, `backups` and the transcripts share.
2. **Copy the deployment** into it. In **System → Shell**:

   ```bash
   cd /mnt/tank/apps/plane
   curl -fsSLO https://raw.githubusercontent.com/AKolenda/plane/preview/deployments/novapro/docker-compose.yml
   curl -fsSLO https://raw.githubusercontent.com/AKolenda/plane/preview/deployments/novapro/backup.sh
   curl -fsSLO https://raw.githubusercontent.com/AKolenda/plane/preview/deployments/novapro/restore.sh
   curl -fsSL -o .env https://raw.githubusercontent.com/AKolenda/plane/preview/deployments/novapro/.env.example
   ```

3. **Edit `.env`:**
   - Set every `change-me` (generate with `openssl rand -hex 32`).
   - Set `WEB_URL=http://<truenas address>:8080`.
   - To keep data on datasets instead of Docker volumes, set `PLANE_PGDATA=/mnt/tank/apps/plane/pgdata`, `PLANE_UPLOADS=/mnt/tank/apps/plane/uploads` and `PLANE_BACKUP_DIR=/mnt/tank/apps/plane/backups`.
   - For the transcript importer, set `TRANSCRIPT_HOST_DIR` to the share's dataset path (e.g. `/mnt/tank/shares/transcripts`). The importer only reads it.
4. If the GHCR packages are private, run `docker login ghcr.io` once in the TrueNAS shell (see **Images** above).
5. **Install the app:** go to **Apps → Discover Apps → ⋮ → Install via YAML**, name it `plane`, and paste:

   ```yaml
   include:
     - path: /mnt/tank/apps/plane/docker-compose.yml
       env_file: /mnt/tank/apps/plane/.env
       project_directory: /mnt/tank/apps/plane
   ```

6. **Save.** The first start pulls the images and runs migrations; it takes a few minutes. Open `WEB_URL`.

To change settings, edit `.env` and use the app's **Edit** then **Save**, or **Stop**/**Start**, so the stack is recreated. To upgrade, use **Update**, or `docker compose -p ix-plane pull` in the shell, and restart the app.

### First run

1. Open `<WEB_URL>/god-mode/` and create the instance admin.
2. Open `WEB_URL`, create the workspace and projects, and invite people.
3. Optionally:
   - configure the GitHub integration ([guide](github-integration.md));
   - create an API token for the transcript importer and the notification app;
   - add the outbound webhook for the notification app under **Workspace settings → Webhooks**.

## API endpoint reference

Public API (header `X-Api-Key`):

| Method and path                                                                                 | Purpose                                                             |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `POST /api/v1/workspaces/<slug>/work-items/import/`                                             | Create or update work items from external sources (single or batch) |
| `GET /api/v1/workspaces/<slug>/digest/`                                                         | Per-user digest                                                     |
| `GET /api/v1/workspaces/<slug>/projects/<project_id>/custom-properties/`                        | Custom property definitions                                         |
| `GET, PATCH /api/v1/workspaces/<slug>/projects/<project_id>/work-items/<id>/custom-properties/` | A work item's custom property values, by key                        |

Web app API (session cookie), used by the UI:

| Method and path                                                                               | Purpose                                                  |
| --------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `GET, POST /api/workspaces/<slug>/projects/<project_id>/custom-properties/`                   | List (members), create (project admins)                  |
| `PATCH, DELETE /api/workspaces/<slug>/projects/<project_id>/custom-properties/<id>/`          | Update or delete (project admins)                        |
| `GET /api/workspaces/<slug>/projects/<project_id>/custom-property-values/[?issue_ids=a,b]`    | Values for many work items, keyed by work item id        |
| `GET, PATCH /api/workspaces/<slug>/projects/<project_id>/issues/<id>/custom-property-values/` | One work item's values, keyed by property id or key      |
| `GET /api/workspaces/<slug>/work-items/<id>/locate/`                                          | Resolve a work item id for stable links                  |
| GitHub integration endpoints                                                                  | Listed in [github-integration.md](github-integration.md) |

Called by GitHub: `GET /api/integrations/github/callback/`, `POST /api/integrations/github/webhook/` and `POST /api/integrations/github/webhook/<connection_id>/`.

## Environment variable reference

Variables this fork adds or relies on. In the Compose deployment they all go in `deployments/novapro/.env`; for local development the API reads `apps/api/.env`.

**API (`apps/api`)**

| Variable                               | Default   | Purpose                                                                                      |
| -------------------------------------- | --------- | -------------------------------------------------------------------------------------------- |
| `APP_BASE_URL`                         | `WEB_URL` | Base of links in imports, digests and stable links (set to `WEB_URL` by the Compose file)    |
| `WEBHOOK_ALLOWED_HOSTS`                | empty     | Internal hostnames webhooks may call                                                         |
| `WEBHOOK_ALLOWED_IPS`                  | empty     | Internal IPs or CIDRs webhooks may call                                                      |
| `GITHUB_INTEGRATION_*`, `GITHUB_APP_*` | empty     | GitHub integration; see [github-integration.md](github-integration.md#environment-variables) |

**Compose deployment (`deployments/novapro/.env`)**, in addition to upstream's `SECRET_KEY`, `LIVE_SERVER_SECRET_KEY`, `POSTGRES_*`, `RABBITMQ_*`, `AWS_*`, `DATABASE_URL`, `REDIS_URL`, `AMQP_URL`, `USE_MINIO`, `FILE_SIZE_LIMIT`, `GUNICORN_WORKERS`, `API_KEY_RATE_LIMIT`, `SITE_ADDRESS`, `APP_DOMAIN`, `CERT_*` and `TRUSTED_PROXIES`:

| Variable                                                                                                                                                                                                       | Default                                              | Purpose                                            |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | -------------------------------------------------- |
| `WEB_URL`                                                                                                                                                                                                      | required                                             | Address people use, with port                      |
| `PLANE_HTTP_PORT` / `PLANE_HTTPS_PORT`                                                                                                                                                                         | `8080` / `8443`                                      | Published proxy ports                              |
| `PLANE_IMAGE_REGISTRY`                                                                                                                                                                                         | `ghcr.io/akolenda`                                   | Where the fork's images live                       |
| `PLANE_IMAGE_TAG`                                                                                                                                                                                              | `latest`                                             | Image tag, e.g. `sha-<commit>` to pin              |
| `PLANE_PULL_POLICY`                                                                                                                                                                                            | `missing`                                            | `always` to pull on every start                    |
| `PLANE_BUNDLED_DB_REPLICAS`, `…_REDIS_…`, `…_MQ_…`, `…_STORAGE_…`                                                                                                                                              | `1`                                                  | `0` to use an external service                     |
| `PLANE_PGDATA`, `PLANE_UPLOADS`                                                                                                                                                                                | Docker volumes                                       | Host paths (datasets) for database and upload data |
| `PLANE_BACKUP_REPLICAS`                                                                                                                                                                                        | `1`                                                  | `0` turns off scheduled backups                    |
| `PLANE_BACKUP_DIR`                                                                                                                                                                                             | `./backups`                                          | Where dumps go                                     |
| `BACKUP_INTERVAL_HOURS`                                                                                                                                                                                        | `24`                                                 | Hours between backups                              |
| `BACKUP_RETENTION_DAYS`                                                                                                                                                                                        | `14`                                                 | Days to keep dumps; `0` keeps all                  |
| `TRANSCRIPT_IMPORTER_REPLICAS`                                                                                                                                                                                 | `0`                                                  | `1` runs the transcript importer                   |
| `TRANSCRIPT_HOST_DIR`                                                                                                                                                                                          | `./transcripts`                                      | Host folder watched (mounted read-only)            |
| `TRANSCRIPT_PLANE_API_KEY`, `TRANSCRIPT_WORKSPACE_SLUG`, `TRANSCRIPT_PROJECT`                                                                                                                                  | empty                                                | Where the importer sends work items                |
| `TRANSCRIPT_LABELS`, `TRANSCRIPT_ASSIGNEES`, `TRANSCRIPT_SOURCE_URL_BASE`, `TRANSCRIPT_POLL_SECONDS`, `TRANSCRIPT_SETTLE_SECONDS`, `TRANSCRIPT_LLM_BASE_URL`, `TRANSCRIPT_LLM_MODEL`, `TRANSCRIPT_LLM_API_KEY` | see [README](../tools/transcript-importer/README.md) | Importer behaviour                                 |

**Backup scripts**: `DATABASE_URL`, `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, `BACKUP_INTERVAL_HOURS`.

## Setup checklist

1. Deploy with `deployments/novapro` (above), open `/god-mode/` and create the instance admin, then the workspace and projects.
2. Per project, add custom properties under **Project settings → Custom properties**.
3. Create API tokens (**Profile settings → Personal access tokens**) for:
   - the Slack/transcript import jobs;
   - the desktop notification app, which reads the digest. Use a workspace admin's token if it reads other people's digests.
4. Transcript importer:
   - set `TRANSCRIPT_IMPORTER_REPLICAS=1`, `TRANSCRIPT_HOST_DIR`, `TRANSCRIPT_PLANE_API_KEY`, `TRANSCRIPT_WORKSPACE_SLUG`, `TRANSCRIPT_PROJECT` and `TRANSCRIPT_ASSIGNEES`;
   - restart the stack.
5. Webhooks:
   - add one under **Workspace settings → Webhooks** with work item events enabled;
   - store its secret key in the receiver and verify `X-Plane-Signature`;
   - allow internal receivers with `WEBHOOK_ALLOWED_HOSTS`.
6. GitHub: follow [github-integration.md](github-integration.md).
7. Check that backups appear in `PLANE_BACKUP_DIR`, and snapshot the uploads dataset.

## Tests

```bash
# API (Django); the NovaPro and GitHub suites, or drop the paths for everything
docker compose -f docker-compose-test.yml run --rm --build api-tests \
  pytest plane/tests/unit/novapro plane/tests/unit/integrations

# Transcript importer
cd tools/transcript-importer && python -m unittest discover -s tests -t .
```
