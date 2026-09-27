# Jenkins development deployment

Use `JenkinsDev` as the SCM pipeline Script Path. Defaults match the existing
scraper deployment: agent `docker-flyio-eu-1`, Docker network
`nginx-proxy-manager`, NPM URL `https://npm-domain.flyio.ai`, and username/password
credential `NPM_CREDENTIAL`. The dedicated enabled proxy host for
`dev-flyio-ai-llm.flyio.ai` and its TLS certificate must already exist.

The pipeline builds a numbered image, starts a candidate on internal port 8000,
checks it, then switches the existing NPM upstream. Failed promotion attempts
restore the previous upstream. Old containers are retained until promotion is verified, then cleaned up. Do not stop them without checking
which upstream NPM is using. Builds of this job run serially.

## Environment credential

Upload a Secret file with ID `env-dev-flyio-ai-llm`. Use unquoted `KEY=value`
lines (unlike the quoted dotenv examples in `.env.example`), without `export`
or shell interpolation. The pipeline injects it with Docker `--env-file` and
overrides only `ENVIRONMENT=development` and `PORT=8000`. Credentials are not
copied into the image or printed.

Set `SERVICE_API_KEY` to the admin's `LLM_SERVICE_API_KEY`. Supply reachable
Qdrant/PostgreSQL URLs and provider settings. `localhost` inside this container
means the candidate itself. Set `DATABASE_ENABLED=false` explicitly if tracking
is not wanted; when enabled, `DATABASE_URL` is required by deployment checks.
Use a development database and collection. This pipeline deploys only the API;
it does not start, replace, or create storage volumes for Qdrant or PostgreSQL.
Those services must already run and manage their own persistence.

## Checks and limitations

Before switching NPM, checks require repeated basic health, Qdrant connectivity
and collection existence, PostgreSQL connectivity when enabled, rejection of
unauthenticated requests, and acceptance of the configured service key. Known
provider names and required API-key presence are checked. Local embeddings also
run one embedding and verify its configured dimension (up to ten minutes for
all candidate checks). This can download weights into the candidate's default
cache, which is not persisted across releases. It does not warm the API
process's RAM model cache. No paid provider calls or vector writes are performed
by the checks, so external API-key validity is not established.

Startup may initialize the Qdrant collection and PostgreSQL schema. NPM rollback
does not undo database/schema changes. Keep those compatible with old releases.
The public post-switch check verifies `/health`; it is not release-specific.
All helper HTTP requests use `Flyio-Jenkins-Deploy/1.0` for the Cloudflare rule.

Run helper tests with:

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Live Docker/Jenkins/NPM deployment is separate from these local helper tests.


## Successful-deployment cleanup

After promotion passes, Jenkins rechecks the NPM upstream and public health,
then stops/removes older containers labelled for this development service.
The current candidate and newer containers are excluded. Old unused images
are removed when Docker permits it; no forced deletion or global pruning runs.
Failed promotion skips cleanup so rollback candidates remain. Cleanup errors
mark the build unstable without rolling back the healthy deployment.

No volumes are deleted. In admin, `flyio-admin-dev-uploads` remains mounted
across releases. Other projects' data volumes are not touched. Removing old
containers discards their process memory and writable container filesystem;
scraper jobs still running there are lost. After cleanup, immediate rollback
to those containers is no longer available. Docker gives running containers
30 seconds to stop before terminating them. Use one pipeline job per domain.
