"""Remove older development releases only after rechecking the active upstream.

Never prunes or removes volumes. No forced image deletion.
"""
import json
import os
import subprocess

from deploy_dev import connect, upstream, verify_public


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def cleanup():
    candidate = os.environ["CANDIDATE"]
    active = json.loads(docker("inspect", candidate))[0]
    service = os.environ["CLEANUP_SERVICE"]
    if service not in {"scraper-dev", "admin-dev", "llm-dev"}:
        raise RuntimeError("Invalid cleanup service")
    if active["Config"].get("Labels", {}).get("flyio.service") != service or not active["State"]["Running"]:
        raise RuntimeError("Candidate is not a running release of this service")
    _, _, host = connect()
    if upstream(host)["forward_host"] != candidate:
        raise RuntimeError("NPM no longer points at this candidate; cleanup refused")
    verify_public()
    ids = docker("ps", "-aq", "--filter", "label=flyio.service=" + service).splitlines()
    images = set()
    for container_id in ids:
        old = json.loads(docker("inspect", container_id))[0]
        if old["Id"] == active["Id"] or old["Created"] >= active["Created"]:
            continue
        # Recheck ownership even though the Docker listing is label-filtered.
        if old["Config"].get("Labels", {}).get("flyio.service") != service:
            continue
        print("Removing old release:", old["Name"].lstrip("/"), flush=True)
        if old["State"]["Running"]:
            subprocess.run(["docker", "stop", "--time", "30", old["Id"]], check=True)
        subprocess.run(["docker", "rm", old["Id"]], check=True)  # no -v
        images.add(old["Image"])
    for image_id in images - {active["Image"]}:
        if docker("ps", "-aq", "--filter", "ancestor=" + image_id):
            continue
        # Docker refuses images still referenced elsewhere. Do not force/prune.
        result = subprocess.run(["docker", "image", "rm", image_id], capture_output=True)
        if result.returncode:
            print("Retained an image Docker could not remove safely.")
    print("Old-release cleanup finished; volumes were preserved.")


if __name__ == "__main__":
    cleanup()
