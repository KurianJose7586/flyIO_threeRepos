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
    # Read the key inside the container; never expose it in process arguments.
    code = '''
import json, os, urllib.request, urllib.error
base = "http://127.0.0.1:8080"
with urllib.request.urlopen(base + "/health", timeout=5) as r:
    assert json.load(r)["status"] == "ok"
key = os.environ.get("SERVICE_API_KEY", "")
assert key, "SERVICE_API_KEY is missing"
req = urllib.request.Request(base + "/scrape/jobs/deployment-readiness", headers={"X-Service-API-Key": key})
try:
    urllib.request.urlopen(req, timeout=5)
except urllib.error.HTTPError as e:
    assert e.code == 404, "Authenticated readiness check failed"
else:
    raise RuntimeError("Unexpected readiness response")
'''
    successes = 0
    for _ in range(30):
        result = subprocess.run(
            ["docker", "exec", os.environ["CANDIDATE"], "python", "-c", code],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
        )
        successes = successes + 1 if result.returncode == 0 else 0
        if successes >= 3:
            print("Candidate passed health and authenticated API checks.")
            return
        time.sleep(3)
    raise RuntimeError("Candidate failed readiness checks; NPM was not changed")


def verify_public():
    for _ in range(12):
        try:
            health = request("https://" + os.environ["SERVICE_DOMAIN"] + "/health")
            if health.get("status") == "ok":
                return
        except (OSError, ValueError):
            pass
        time.sleep(3)
    raise RuntimeError("Public HTTPS health check failed")


def promote():
    endpoint, headers, host = connect()
    previous = upstream(host)
    target = {"forward_scheme": "http", "forward_host": os.environ["CANDIDATE"], "forward_port": 8080}
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
