#!/usr/bin/env python
"""Run remote command on VPS via paramiko using passphrase-protected key."""
import sys, paramiko, pathlib

KEY = pathlib.Path.home() / ".ssh" / "id_ed25519"
HOST = "139.162.9.224"
USER = "root"
PASSPHRASE = "23112007"

def run(cmd: str) -> int:
    pk = paramiko.Ed25519Key.from_private_key_file(str(KEY), password=PASSPHRASE)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, pkey=pk, timeout=30)
    stdin, stdout, stderr = c.exec_command(cmd, timeout=120)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    c.close()
    return rc

if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
