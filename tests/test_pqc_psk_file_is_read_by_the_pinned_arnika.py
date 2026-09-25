"""PQC_PSK_FILE is only exported while the pinned arnika still reads it.

arnika's maintainer said on 2026-09-16 that the file-based PQC handover will be
replaced by PQC-HPKE, and upstream PR #51 removes it: its INSTALL.md calls
PQC_PSK_FILE "ignored". This repository's WireGuard lane depends on that
variable -- Rosenpass writes the file and arnika reads it -- so a pin bump past
#51 would leave every node exporting a variable nothing reads, the PQC half
silently absent from the HKDF input, and no error anywhere.

This fails on exactly that combination: the compose files and node scripts
still set PQC_PSK_FILE while the pinned arnika's config no longer mentions it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG_GO = ROOT / "submodules" / "arnika" / "config" / "config.go"
USERS = ["docker-compose.yml", "docker-compose.multihop.yml", "docker-compose.strongswan.yml",
         "nodes/alice/entrypoint.sh", "nodes/strongswan/entrypoint.sh"]


def test_exported_only_while_the_pin_reads_it():
    if not CONFIG_GO.is_file():
        pytest.skip("arnika submodule not checked out")
    users = [u for u in USERS if "PQC_PSK_FILE" in (ROOT / u).read_text()]
    assert users, "nothing sets PQC_PSK_FILE any more; delete this test with the migration"
    assert '"PQC_PSK_FILE"' in CONFIG_GO.read_text(), (
        f"the pinned arnika no longer reads PQC_PSK_FILE, but {users} still set it. "
        "This is the PQC-HPKE migration of upstream PR #51: the Rosenpass file "
        "handover is gone, so the PQC half of the key would silently drop out. "
        "Migrate the lane before moving the pin.")
