#!/usr/bin/env python3
"""Test the Step the way the Bitrise CLI runs it.

The CLI exports every input as an environment variable with the input's name
and runs step.sh with bash. This runner does the same against a stand-in API
(tests/fake_api.py), with a fake envman on PATH that records the outputs.

The happy path also runs in the real CLI: `bitrise run test` (see bitrise.yml).
This runner covers the file layout and the cases that must fail.

Usage:
    python tests/run_tests.py
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STEP_SH = os.path.join(ROOT, "step.sh")
API_KEY = "test-key-2f8a1c"

# On Windows the bare name "bash" can reach the WSL bash, which does not get
# the environment the test sets. Use Git Bash there.
BASH = shutil.which("bash") or "bash"
if os.name == "nt":
    _git_bash = "C:/Program Files/Git/usr/bin/bash.exe"
    if os.path.exists(_git_bash):
        BASH = _git_bash

INPUT_NAMES = ["docs_path", "asyntai_api_key", "file_patterns", "exclude",
               "title_prefix", "website_id", "prune", "dry_run", "base_url"]

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  PASS  %s" % name)
    else:
        FAILED.append((name, detail))
        print("  FAIL  %s" % name)
        if detail:
            print("        %s" % str(detail)[:600])


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def write_exe(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.chmod(path, 0o755)


def make_docs(base):
    docs = os.path.join(base, "src", "docs")
    os.makedirs(os.path.join(docs, "guides"))
    os.makedirs(os.path.join(docs, "drafts"))
    files = {
        "index.md": "# Welcome\n\nAsyntai answers questions on your website.",
        "guides/setup.md": "# Setup\n\nPaste the script tag before the body ends.",
        "drafts/wip.md": "# Draft\n\nThis page is not ready for readers yet.",
        "CHANGELOG.md": "# Changelog\n\n1.0.0 is the first version.",
        "tiny.md": "short",
        "api.rst": "API reference written in reStructuredText format.",
    }
    for name, text in files.items():
        with open(os.path.join(docs, name), "w", encoding="utf-8") as handle:
            handle.write(text)
    return docs


class Api:
    def __init__(self, workdir):
        self.port = free_port()
        self.dump = os.path.join(workdir, "api-%d.json" % self.port)
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "fake_api.py"),
             str(self.port), self.dump])
        for _ in range(100):
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.05)
        raise RuntimeError("the stand-in API did not start")

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.port

    def state(self):
        flag = self.dump + ".flush"
        open(flag, "w").close()
        for _ in range(100):
            if not os.path.exists(flag):
                break
            time.sleep(0.05)
        with open(self.dump, encoding="utf-8") as handle:
            return json.load(handle)

    def stop(self):
        open(self.dump + ".stop", "w").close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def run_step(inputs, workdir, shim_dir, source_dir, cwd=None):
    env = dict(os.environ)
    for name in INPUT_NAMES + ["ASYNTAI_API_KEY", "BITRISE_SOURCE_DIR"]:
        env.pop(name, None)
    env["PATH"] = shim_dir + os.pathsep + env.get("PATH", "")
    env["BITRISE_SOURCE_DIR"] = source_dir.replace(os.sep, "/")
    env["ENVMAN_LOG"] = os.path.join(workdir, "envman.log").replace(os.sep, "/")
    env.update(inputs)
    if os.path.exists(env["ENVMAN_LOG"].replace("/", os.sep)):
        os.remove(env["ENVMAN_LOG"].replace("/", os.sep))
    result = subprocess.run([BASH, STEP_SH.replace(os.sep, "/")],
                            cwd=cwd or workdir, env=env,
                            capture_output=True, text=True)
    outputs = {}
    log = env["ENVMAN_LOG"].replace("/", os.sep)
    if os.path.exists(log):
        with open(log, encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.rstrip("\n").partition("=")
                outputs[key] = value
    return result, outputs


def check_layout():
    print("Layout")
    with open(os.path.join(ROOT, "step.yml"), encoding="utf-8") as handle:
        step = yaml.safe_load(handle)
    for field in ("title", "summary", "description", "website",
                  "source_code_url", "support_url", "type_tags", "inputs"):
        check("step.yml has %s" % field, step.get(field))
    check("toolkit is bash with step.sh",
          step.get("toolkit", {}).get("bash", {}).get("entry_file") == "step.sh")
    check("support_url is the issue tracker",
          step["support_url"] == step["source_code_url"] + "/issues")
    names = [next(k for k in item if k != "opts") for item in step["inputs"]]
    check("inputs are the expected set", sorted(names) == sorted(INPUT_NAMES),
          names)
    script = open(STEP_SH, encoding="utf-8").read()
    for name in names:
        check("step.sh reads %s" % name, "${%s" % name in script)
    key = [i for i in step["inputs"] if "asyntai_api_key" in i][0]
    check("API key input is sensitive", key["opts"].get("is_sensitive") is True)
    check("API key default reads a Secret", key["asyntai_api_key"] == "$ASYNTAI_API_KEY")
    outputs = [next(iter(o)) for o in step.get("outputs", [])]
    check("output ASYNTAI_DOCS_SYNC_SUMMARY declared",
          outputs == ["ASYNTAI_DOCS_SYNC_SUMMARY"], outputs)
    check("step.sh exports the output with envman",
          "envman add --key ASYNTAI_DOCS_SYNC_SUMMARY" in script)
    for flag in ("prune", "dry_run"):
        item = [i for i in step["inputs"] if flag in i][0]
        check("%s offers yes/no" % flag,
              item["opts"].get("value_options") == ["yes", "no"])
    with open(os.path.join(ROOT, "bitrise.yml"), encoding="utf-8") as handle:
        flow = yaml.safe_load(handle)
    for wf in ("test", "audit-this-step", "share-this-step"):
        check("bitrise.yml has workflow %s" % wf, wf in flow["workflows"])
    for path in ("README.md", "LICENSE", "CHANGELOG.md", "sync.py", "step.sh"):
        check("file %s exists" % path, os.path.exists(os.path.join(ROOT, path)))
    for path in ("step.sh", "sync.py", "step.yml", "bitrise.yml"):
        raw = open(os.path.join(ROOT, path), "rb").read()
        check("%s has LF line ends" % path, b"\r\n" not in raw)
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    check("README links the setup guide",
          "asyntai.com/documentation/integrations/bitrise/" in readme)
    check("README version matches CHANGELOG",
          "@1.0.0:" in readme and
          "## 1.0.0" in open(os.path.join(ROOT, "CHANGELOG.md"),
                             encoding="utf-8").read())


def check_behaviour():
    workdir = tempfile.mkdtemp(prefix="asyntai-bitrise-")
    shim_dir = os.path.join(workdir, "shim")
    os.makedirs(shim_dir)
    write_exe(os.path.join(shim_dir, "python3"),
              '#!/bin/sh\nexec "%s" "$@"\n' % sys.executable.replace(os.sep, "/"))
    # Fake envman: records "add --key K --value V" as K=V.
    write_exe(os.path.join(shim_dir, "envman"), """#!/bin/sh
key=""; value=""
while [ $# -gt 0 ]; do
  case "$1" in
    --key) key="$2"; shift 2 ;;
    --value) value="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf '%s=%s\\n' "$key" "$value" >> "$ENVMAN_LOG"
""")
    docs = make_docs(workdir)
    source = os.path.join(workdir, "src")
    api = Api(workdir)
    base = {"asyntai_api_key": API_KEY, "base_url": api.url,
            "prune": "no", "dry_run": "no",
            "file_patterns": "*.md,*.mdx,*.txt"}
    try:
        print("Behaviour")

        res, out = run_step(dict(base, docs_path="docs",
                                 exclude="drafts/*,CHANGELOG.md",
                                 title_prefix="Docs / "),
                            workdir, shim_dir, source)
        check("relative path is read from BITRISE_SOURCE_DIR",
              res.returncode == 0, res.stdout + res.stderr)
        check("first run adds 2, skips the short file",
              out.get("ASYNTAI_DOCS_SYNC_SUMMARY") ==
              "Done. 2 added, 0 updated, 0 unchanged, 0 deleted, 1 skipped.",
              out)
        titles = sorted(e["title"] for e in api.state()["entries"])
        check("exclude list skips drafts and CHANGELOG",
              titles == ["Docs / guides/setup.md", "Docs / index.md"], titles)
        check("API key is not printed", API_KEY not in res.stdout + res.stderr)

        # An absolute path as bash sees it (Git Bash: /c/Users/...).
        abs_docs = docs.replace(os.sep, "/")
        if os.name == "nt" and re.match(r"^[A-Za-z]:/", abs_docs):
            abs_docs = "/" + abs_docs[0].lower() + abs_docs[2:]
        res, out = run_step(dict(base, docs_path=abs_docs, exclude="drafts/*",
                                 title_prefix="Docs / ", file_patterns="*.rst"),
                            workdir, shim_dir, source)
        check("absolute path and own patterns work",
              res.returncode == 0 and "Done. 1 added" in
              out.get("ASYNTAI_DOCS_SYNC_SUMMARY", ""), res.stdout + res.stderr)

        res, out = run_step(dict(base, docs_path="docs", prune="yes",
                                 file_patterns="*.rst"),
                            workdir, shim_dir, source)
        # 3 entries from the runs above, plus "api.rst" with no prefix.
        titles = sorted(e["title"] for e in api.state()["entries"])
        check("prune without a title prefix removes nothing",
              res.returncode == 0 and "prune was ignored" in res.stdout and
              titles == ["Docs / api.rst", "Docs / guides/setup.md",
                         "Docs / index.md", "api.rst"], titles)

        res, out = run_step(dict(base, docs_path="docs", asyntai_api_key=""),
                            workdir, shim_dir, source)
        check("empty key fails", res.returncode != 0)
        check("empty key names the Bitrise Secret",
              "Bitrise Secret named ASYNTAI_API_KEY" in res.stdout + res.stderr, res.stdout + res.stderr)
        check("empty key error becomes the output",
              out.get("ASYNTAI_DOCS_SYNC_SUMMARY", "").startswith("Error:"), out)

        res, out = run_step(dict(base, docs_path="docs",
                                 asyntai_api_key="wrong-key"),
                            workdir, shim_dir, source)
        check("wrong key fails with HTTP 401",
              res.returncode != 0 and "HTTP 401" in res.stdout + res.stderr, res.stdout + res.stderr)

        res, _ = run_step(dict(base, docs_path=""), workdir, shim_dir, source)
        check("empty path fails",
              res.returncode != 0 and "needs a Documentation path" in res.stdout + res.stderr,
              res.stderr)

        res, _ = run_step(dict(base, docs_path="nowhere"),
                          workdir, shim_dir, source)
        check("missing folder fails",
              res.returncode != 0 and "does not exist" in res.stdout + res.stderr, res.stdout + res.stderr)

        res, _ = run_step(dict(base, docs_path="docs", file_patterns="*.adoc"),
                          workdir, shim_dir, source)
        check("no matching file fails",
              res.returncode != 0 and "no file under" in res.stdout + res.stderr, res.stdout + res.stderr)

        for flag, value in (("prune", "true"), ("dry_run", "1")):
            res, _ = run_step(dict(base, docs_path="docs", **{flag: value}),
                              workdir, shim_dir, source)
            check("%s=%s is rejected" % (flag, value),
                  res.returncode != 0 and "must be yes or no" in res.stdout + res.stderr,
                  res.stderr)

        calls_before = len(api.state()["calls"])
        res, out = run_step(dict(base, docs_path="docs", dry_run="yes",
                                 asyntai_api_key=""),
                            workdir, shim_dir, source)
        check("dry run works without a key",
              res.returncode == 0 and out.get("ASYNTAI_DOCS_SYNC_SUMMARY") ==
              "Dry run. Nothing was sent.", res.stdout + res.stderr)
        check("dry run makes no API call",
              len(api.state()["calls"]) == calls_before)

        res, out = run_step(dict(base, docs_path="docs",
                                 base_url="http://127.0.0.1:%d" % free_port()),
                            workdir, shim_dir, source)
        check("unreachable API fails with a clear error",
              res.returncode != 0 and "Cannot reach" in res.stdout + res.stderr, res.stdout + res.stderr)
    finally:
        api.stop()
        shutil.rmtree(workdir, ignore_errors=True)


def main():
    check_layout()
    check_behaviour()
    print("")
    print("%d passed, %d failed" % (len(PASSED), len(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
