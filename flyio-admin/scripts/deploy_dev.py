"""Jenkins development deployment helper; Python standard library only.

NPM must share DOCKER_NETWORK with the candidate. Uses the NPM v2 API;
preflight verifies login and the existing proxy host before the image build.
No credentials or full NPM responses are printed or written to disk.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


def request(url, method="GET", payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method=method,
        # Identifies deployment requests for the Cloudflare rule.
        headers={"Content-Type": "application/json", "User-Agent": "Flyio-Jenkins-Deploy/1.0", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def connect():
    base = os.environ["NPM_URL"].rstrip("/")
    if not base.startswith("https://"):
        raise RuntimeError("NPM_URL must use HTTPS to protect NPM credentials")
    token = request(base + "/api/tokens", "POST", {
        "identity": os.environ["NPM_USERNAME"],
        "secret": os.environ["NPM_PASSWORD"],
    })["token"]
    headers = {"Authorization": "Bearer " + token}
    hosts = request(base + "/api/nginx/proxy-hosts", headers=headers)
    matches = [host for host in hosts if os.environ["SERVICE_DOMAIN"] in host.get("domain_names", [])]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one existing NPM proxy host for the development domain")
    endpoint = base + "/api/nginx/proxy-hosts/" + str(int(matches[0]["id"]))
    host = request(endpoint, headers=headers)
    if os.environ["SERVICE_DOMAIN"] not in host.get("domain_names", []):
        raise RuntimeError("NPM proxy host ID does not match the development domain")
    if not host.get("enabled"):
        raise RuntimeError("The existing development proxy host must be enabled")
    if host.get("domain_names") != [os.environ["SERVICE_DOMAIN"]]:
        raise RuntimeError("Use a dedicated proxy host containing only the development domain")
    if host.get("locations"):
        raise RuntimeError("Custom NPM locations need review before automated switching")
    return endpoint, headers, host


def upstream(host):
    return {key: host[key] for key in ("forward_scheme", "forward_host", "forward_port")}


def check_candidate():
    # Node is already installed in the admin image; no Python needed there.
    code = """
(async () => {
  const opts = { signal: AbortSignal.timeout(5000), headers: { 'User-Agent': 'Flyio-Jenkins-Deploy/1.0' } };
  const response = await fetch('http://127.0.0.1:3000/health', opts);
  const health = await response.json();
  if (!response.ok || health.status !== 'ok' || health.db !== 'connected') throw Error('Database health failed');
  const page = await fetch('http://127.0.0.1:3000/admin', { ...opts, signal: AbortSignal.timeout(5000) });
  if (!page.ok || !(await page.text()).includes('<div id="root"')) throw Error('Admin frontend missing');

  // Confirm the LLM service accepts LLM_SERVICE_API_KEY. Its /health and
  // /v1/health are public, so a green health check proves only reachability —
  // a release with the wrong key started cleanly, looked healthy, and then
  // failed every store and generate call with a 401.
  //
  // /v1/api/* is auth-guarded, and auth runs before routing, so a GET on this
  // POST-only route answers 401 when the key is rejected and 405 when it is
  // accepted. Nothing is created or read.
  //
  // This must see the application answer. An earlier version passed on
  // anything that was not a 401, on the reasoning that an unreachable LLM
  // service is its own outage and should not block an admin release. That
  // reasoning was wrong in the case that matters: when LLM_SERVICE_URL itself
  // pointed at the wrong host, the proxy answered 525, the check read "not
  // 401" as success, and a completely non-functional admin was promoted. A
  // wrong URL is admin's own misconfiguration and is exactly what this gate
  // is for. The surrounding loop retries for ~90s, so a brief restart of the
  // LLM service does not fail the build.
  const probe = await fetch(process.env.LLM_SERVICE_URL + '/v1/api/store', {
    ...opts,
    headers: { ...opts.headers, 'X-Service-API-Key': process.env.LLM_SERVICE_API_KEY || '' },
    signal: AbortSignal.timeout(8000),
  });
  if (probe.status === 401) throw Error('LLM service rejected LLM_SERVICE_API_KEY');
  if (probe.status >= 500) throw Error('LLM_SERVICE_URL did not answer as the LLM service');
})().catch(() => process.exit(1));
"""
    successes = 0
    for _ in range(30):
        result = subprocess.run(
            ["docker", "exec", os.environ["CANDIDATE"], "node", "-e", code],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
        )
        # /health only checks PostgreSQL, so also wait for the existing startup
        # completion log. Application readiness/scheduler code is unchanged.
        logs = subprocess.run(
            ["docker", "logs", "--tail", "200", os.environ["CANDIDATE"]],
            capture_output=True, text=True, timeout=10,
        )
        ready = result.returncode == 0 and "[Startup] Ready." in logs.stdout
        successes = successes + 1 if ready else 0
        if successes >= 3:
            print("Candidate passed startup, database health, frontend, and LLM service-key checks.")
            return
        time.sleep(3)
    raise RuntimeError(
        "Candidate failed readiness checks; NPM was not changed. "
        "If the container is otherwise healthy, check LLM_SERVICE_URL points at "
        "the LLM service and that LLM_SERVICE_API_KEY equals SERVICE_API_KEY in "
        "the flyio-ai-llm environment."
    )


def verify_public():
    for _ in range(12):
        try:
            health = request("https://" + os.environ["SERVICE_DOMAIN"] + "/health")
            if health.get("status") == "ok" and health.get("db") == "connected":
                return
        except (OSError, ValueError):
            pass
        time.sleep(3)
    raise RuntimeError("Public HTTPS health check failed")


def promote():
    endpoint, headers, host = connect()
    previous = upstream(host)
    target = {"forward_scheme": "http", "forward_host": os.environ["CANDIDATE"], "forward_port": 3000}
    print("Previous upstream:", json.dumps(previous), flush=True)
    try:
        # Only update upstream fields, preserving the certificate and other settings.
        # Treat a timeout as an uncertain write and attempt rollback as well.
        request(endpoint, "PUT", target, headers)
        current = request(endpoint, headers=headers)
        if upstream(current) != target or current.get("meta", {}).get("nginx_online") is False:
            raise RuntimeError("NPM did not activate the candidate upstream")
        verify_public()
    except Exception:
        print("Promotion failed; restoring previous upstream.", flush=True)
        try:
            request(endpoint, "PUT", previous, headers)
            restored = request(endpoint, headers=headers)
            if upstream(restored) != previous or restored.get("meta", {}).get("nginx_online") is False:
                raise RuntimeError("Rollback did not activate")
            verify_public()
            print("Previous upstream restored and public health verified.", flush=True)
        except Exception:
            raise RuntimeError("ROLLBACK UNCONFIRMED: inspect NPM manually; both containers were retained") from None
        raise RuntimeError("Deployment failed; previous upstream restored") from None
    print("Candidate promoted and public HTTPS health verified.")


if __name__ == "__main__":
    try:
        action = sys.argv[1]
        if action == "preflight":
            connect()
            print("NPM credentials and proxy host verified.")
        elif action == "check":
            check_candidate()
        elif action == "promote":
            promote()
        else:
            raise RuntimeError("Unknown deployment action")
    except Exception as exc:
        # Avoid printing HTTP bodies, which may contain configuration secrets.
        print("Deployment error:", str(exc), file=sys.stderr)
        sys.exit(1)
