#!/usr/bin/env python
"""Write local file to VPS by piping content via ssh exec."""
import sys, paramiko, pathlib, base64

KEY = pathlib.Path.home() / ".ssh" / "id_ed25519"
HOST = "139.162.9.224"
USER = "root"
PASSPHRASE = "23112007"

def put(local: str, remote: str) -> None:
    data = pathlib.Path(local).read_bytes()
    b64 = base64.b64encode(data).decode()
    pk = paramiko.Ed25519Key.from_private_key_file(str(KEY), password=PASSPHRASE)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, pkey=pk, timeout=30)
    cmd = f"mkdir -p $(dirname {remote}) && echo '{b64}' | base64 -d > {remote}"
    stdin, stdout, stderr = c.exec_command(cmd, timeout=60)
    rc = stdout.channel.recv_exit_status()
    err = stderr.read().decode(errors="replace")
    c.close()
    if rc != 0:
        raise SystemExit(f"rc={rc} err={err}")
    print(f"Uploaded {local} -> {remote} ({len(data)} bytes)")

if __name__ == "__main__":
    put(sys.argv[1], sys.argv[2])
