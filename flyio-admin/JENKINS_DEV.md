# Development deployment

Configure the Jenkins SCM pipeline with Script Path `JenkinsDev`. It uses the
same agent (`docker-flyio-eu-1`) and default Docker network
(`nginx-proxy-manager`) as the scraper pipeline.

- Secret file credential: `env-dev-flyio-admin` (Docker `KEY=value` format).
- NPM username/password credential: `NPM_CREDENTIAL`.
- NPM management URL: `https://npm-domain.flyio.ai`.
- Existing dedicated, enabled proxy host and TLS certificate:
  `dev-admin.flyio.ai`. Its ID is discovered automatically.
- Deployment HTTP User-Agent: `Flyio-Jenkins-Deploy/1.0`.

The `.env` credential supplies database, JWT, scraper, and LLM configuration.
Keep `CMS_JWT_SECRET` stable across releases. The development pipeline overrides
`PORT=3000`, `NODE_ENV=production` (serving the built frontend), and
`BLOG_UPLOAD_DIR=/app/uploads/blog`. These overrides apply only to containers
created by this pipeline. Frontend/backend compile during the Docker build;
secrets are injected only when starting the container.

## Development-only uploads

The pipeline creates/reuses named volume `flyio-admin-dev-uploads`, mounted at
`/app/uploads/blog`. All development releases share it, so blog images survive
container replacements and rollback. No existing images need importing.
Production is not configured or modified by this pipeline. Do not attach this
development volume to production. Do not delete it during image/container
cleanup; Docker volumes still require independent backups for host failure.

## Release flow

Jenkins checks NPM credentials and domain configuration, builds a uniquely
tagged image, and starts a candidate without stopping the current container.
It waits for the existing `[Startup] Ready.` log plus repeated database health
and `/admin` HTML checks. This uses Node inside the container and Python 3 on
the Jenkins agent. It then updates only NPM's upstream to the candidate name
on port 3000 and checks public HTTPS database health. If promotion fails, it
attempts to restore the old upstream. Public health is not release-specific.

Application readiness and scheduler code are deliberately unchanged. Both
running containers start their schedulers, so overlap can duplicate job
processing. Cleanup stops old containers after a successful switch. Migrations run on candidate startup against the shared database;
upstream rollback does not undo migrations or shared uploads. Keep migrations
compatible with the old release. This is not a guarantee of uninterrupted
background-job processing.

## Local helper verification

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Live Jenkins/Docker/NPM execution must be checked on the deployment host.


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
