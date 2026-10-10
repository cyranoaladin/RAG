"""Témoin Docker local du pont BFF/API, sans image ni service de production."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from uuid import uuid4

import pytest

_API = r"""
const http = require('node:http');
const routes = new Map([
  ['GET /health', {status:'healthy'}],
  ['GET /collections/readiness', {launch_ready:false}],
  ['GET /collections/v2', {collections:[]}],
  ['POST /search/v2', {results:[], warnings:[]}],
]);
http.createServer((req,res) => {
  const payload = routes.get(`${req.method} ${req.url}`);
  res.writeHead(payload ? 200 : 404, {'content-type':'application/json'});
  res.end(JSON.stringify(payload || {error:'not_found'}));
}).listen(8001, '0.0.0.0');
"""

_DB = "require('node:net').createServer(s=>s.end('db')).listen(5432,'0.0.0.0')"

_RAG_DB_PROBE = r"""
const net = require('node:net');
async function reachable() {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const connected = await new Promise(resolve => {
      const socket = net.connect({host:'pgvector',port:5432,timeout:1000});
      socket.on('connect', () => { socket.destroy(); resolve(true); });
      socket.on('error', () => resolve(false));
      socket.on('timeout', () => { socket.destroy(); resolve(false); });
    });
    if (connected) return true;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  return false;
}
reachable().then(connected => {
  if (!connected) throw new Error('DB unavailable from rag network');
  console.log(JSON.stringify({db_reachable:true}));
}).catch(error => { console.error(error.message); process.exitCode=1; });
"""

_BFF = r"""
const net = require('node:net');
async function main() {
  const deadline = Date.now() + 10000;
  let healthy = false;
  while (Date.now() < deadline) {
    try {
      const response = await fetch('http://ingestor:8001/health', {
        signal: AbortSignal.timeout(1000),
      });
      if (response.status === 200) { healthy = true; break; }
    } catch (_) { /* Le serveur témoin peut encore démarrer. */ }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!healthy) throw new Error('API unavailable from BFF network');
  for (const [method,path] of [
    ['GET','/health'],
    ['GET','/collections/readiness'],
    ['GET','/collections/v2'],
    ['POST','/search/v2'],
  ]) {
    const response = await fetch(`http://ingestor:8001${path}`, {
      method, signal: AbortSignal.timeout(5000),
    });
    if (response.status !== 200) throw new Error(`${method} ${path}: ${response.status}`);
  }
  const refused = await new Promise(resolve => {
    const socket = net.connect({host:process.env.DB_IP,port:5432,timeout:1500});
    socket.on('connect', () => { socket.destroy(); resolve(false); });
    socket.on('error', () => resolve(true));
    socket.on('timeout', () => { socket.destroy(); resolve(true); });
  });
  if (!refused) throw new Error('DB reachable from BFF network');
  try {
    await require('node:dns').promises.lookup('pgvector');
    throw new Error('DB DNS visible from BFF network');
  } catch (error) {
    if (!['ENOTFOUND', 'EAI_AGAIN'].includes(error.code)) throw error;
  }
  console.log(JSON.stringify({api_routes:4,db_ip_refused:true,db_dns_refused:true}));
}
main().catch(error => { console.error(error.message); process.exitCode=1; });
"""


def _docker(*args: str, timeout: int = 30) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False, timeout=timeout
    )
    if result.returncode:
        raise AssertionError(f"docker {args[0]} failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def _assert_database_reachable(rag_net: str, image: str) -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", rag_net, image, "node", "-e", _RAG_DB_PROBE],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr[:500]
    assert json.loads(result.stdout) == {"db_reachable": True}


@pytest.mark.skipif(
    os.environ.get("NEXUS_REQUIRE_DOCKER") != "1" or shutil.which("docker") is None,
    reason="témoin réseau Docker local opt-in",
)
def test_only_api_joins_bff_and_database_networks() -> None:
    suffix = uuid4().hex[:12]
    rag_net = f"nexus-bff-witness-{suffix}-rag"
    bff_net = f"nexus-bff-witness-{suffix}-bff"
    api = f"nexus-bff-witness-{suffix}-api"
    database = f"nexus-bff-witness-{suffix}-db"
    image = os.environ.get("NEXUS_BFF_NETWORK_WITNESS_IMAGE", "node:22-alpine")
    created_networks: list[str] = []
    created_containers: list[str] = []
    try:
        for network in (rag_net, bff_net):
            _docker("network", "create", "--driver", "bridge", network)
            created_networks.append(network)
        _docker("run", "-d", "--rm", "--name", api, "--network", rag_net, image, "node", "-e", _API)
        created_containers.append(api)
        _docker("network", "connect", "--alias", "ingestor", bff_net, api)
        _docker(
            "run",
            "-d",
            "--rm",
            "--name",
            database,
            "--network",
            rag_net,
            "--network-alias",
            "pgvector",
            image,
            "node",
            "-e",
            _DB,
        )
        created_containers.append(database)
        database_ip = _docker(
            "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", database
        ).split()[0]
        _assert_database_reachable(rag_net, image)
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                bff_net,
                "-e",
                f"DB_IP={database_ip}",
                image,
                "node",
                "-e",
                _BFF,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr[:500]
        assert json.loads(result.stdout) == {
            "api_routes": 4,
            "db_ip_refused": True,
            "db_dns_refused": True,
        }
        _assert_database_reachable(rag_net, image)
    finally:
        for container in reversed(created_containers):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
        for network in reversed(created_networks):
            subprocess.run(["docker", "network", "rm", network], capture_output=True, check=False)
