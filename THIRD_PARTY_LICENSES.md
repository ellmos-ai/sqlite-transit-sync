# Third-Party Licenses & Project-Maintained Dependency Inventory

> **Project:** `ellmos-ai/sqlite-transit-sync`<br>
> **Inventory Record Date (project-maintained):** 2026-10-02 (earlier recorded dates: 2026-09-23, 2026-09-11)<br>
> **Repository License:** [MIT License](LICENSE)<br>
> **Plain-Text Inventory Copy:** [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt)<br>
> **Contributing Guidelines:** [CONTRIBUTING.md](CONTRIBUTING.md)<br>
> **Repository Attribution Notice:** [NOTICE](NOTICE)<br>


---

> **Scope:** This is a repository-maintained record of package-license metadata and project-stated behavior. It is not an independent audit, a legal assessment, a standards-conformance statement, or a security certification.

## Inventory Summary & Scope

Project documentation describes `sqlite-transit-sync` as a local-first SQLite synchronization package. Snapshot capture, redaction, configured credential-pattern scanning, digest checks, and row-level merging are performed by its local process. The process inherits the operating-system permissions of its launcher; this inventory does not claim standard-user enforcement or privilege certification.

The package/license records below list the license identifiers recorded for declared direct, optional, and development packages (including MIT, Apache-2.0, BSD-3-Clause, and PSFL-2.0). They are project-maintained records, not an independent review of license coverage or legal compatibility.

### Invariant Cross-Reference Matrix

| Project Invariant ID | Project-Stated Behavior | Source / Implementation Reference | Recorded License Attribution |
|:---|:---|:---|:---|
| `INV-LOCAL-01` | **Local SQLite processing and configured transit path** | Reads local SQLite files and publishes snapshots to the configured transit path. That path may be shared or network-mounted; host and transport behavior are outside this module. | [PSFL-2.0](https://docs.python.org/3/license.html) |
| `INV-SNAP-02` | **Snapshot file publication** | Captures an online backup and publishes the snapshot file through a temporary file and `os.replace`; the manifest is written separately. | [PSFL-2.0](https://docs.python.org/3/license.html) |
| `INV-ROLL-03` | **Rollback Journal Clean Isolation** | Backups closed in rollback-journal mode; fail-closed purge of `-wal`, `-shm`, and `-journal` sidecars | [PSFL-2.0](https://docs.python.org/3/license.html) |
| `INV-PATH-04` | **Strict Transit Path Containment** | Rejection of directory traversal (`../`), absolute paths, symlinks, and reparse points | [PSFL-2.0](https://docs.python.org/3/license.html) |
| `INV-VERIFY-05` | **Snapshot integrity checks** | Compares snapshot size and SHA-256 with the manifest and runs SQLite `PRAGMA quick_check`; SHA-256 alone does not authenticate the sender. | [PSFL-2.0](https://docs.python.org/3/license.html) |
| `INV-SHIELD-06` | **Configured credential-pattern scan** | Checks configured patterns (including defaults from `credential-triggers.json`); a match can abort publication. It is a safety net, not an exhaustive secret detector. | [PSFL-2.0](https://docs.python.org/3/license.html) |
| `INV-HMAC-07` | **Optional manifest authentication** | HMAC is added and verified only when a compatible authenticator is configured; SHA-256 alone is an integrity check, not sender authentication. | [PSFL-2.0](https://docs.python.org/3/license.html) |
| `INV-MERGE-08` | **Deterministic Row-Level Merge** | Transactional row-level merge (LWW per PK, shared column union for schema drift, tombstone policy) | [MIT](LICENSE) |
| `INV-RET-09` | **Conservative Retention Scoping** | Snapshot cleanup is dry-run by default, scoped strictly to local node artifacts | [MIT](LICENSE) |
| `INV-SLA-10` | **Process Permissions & Security Response Policy** | Inherits the caller's operating-system permissions; no standard-user or elevation enforcement is claimed | [SECURITY.md](SECURITY.md) |

---

## Recorded Dependency-License Scope & Process Permissions

1. **Declared dependency-license scope:** The inventory records the license identifiers reported for the packages listed below. This record is not an independent assessment of transitive dependency coverage or legal compatibility.
2. **Zero-Runtime-Dependency Core:** The core synchronization engine requires **zero** external runtime dependencies (`dependencies = []` in `pyproject.toml`). All core primitives (snapshotting, redaction, hashing, HMAC, merging, retention) rely entirely on standard library modules.
3. **Process permissions:** The process inherits the operating-system permissions of its launcher. The source does not implement standard-user enforcement or request privilege elevation.
4. **Configured transit boundary:** The module reads local SQLite databases and exchanges snapshot files through the configured filesystem path. That path may be a local directory, shared folder, or network-mounted location; host, mount, and sync-service behavior are outside the module. This inventory does not assert zero network egress.

---

## Runtime Architecture & Dependencies

`sqlite-transit-sync` is a local-first SQLite synchronization engine that exchanges snapshot files through a configured filesystem transit path. Its core push, pull, and merge operations have zero external runtime dependencies; behavior of a shared or network-mounted path is outside this module.

### Zero-Runtime-Dependency Guarantee (Core Engine)

| Package | Version Spec | License | Type | Purpose |
|---------|-------------|---------|------|---------|
| *None* | `n/a` | `n/a` | External | The core `sqlite-transit-sync` engine has **0** external runtime dependencies (`dependencies = []` in `pyproject.toml`). Push, pull, merge, retention cleanup, and projection verification rely exclusively on Python standard library modules. |
| *Python Standard Library* | `>=3.10` | PSF License | Built-in | `argparse`, `dataclasses`, `datetime`, `hashlib`, `hmac`, `json`, `os`, `pathlib`, `re`, `shutil`, `sqlite3`, `sys`, `typing`, `uuid` |

### Optional Runtime Dependencies

For the encrypted showcase layer (**Republica**) and sealed envelopes, users may opt in to `[crypto]`. Applications that choose OS-native HMAC key lookup may opt in to `[keyring]`; injected custom resolvers keep the core dependency-free:

| Package | Version Spec | License | Type | Purpose |
|---------|-------------|---------|------|---------|
| [cryptography](https://github.com/pyca/cryptography) | `>=42` | Apache-2.0 OR BSD-3-Clause | Optional Extra (`[crypto]`) | Authenticated symmetric Fernet encryption for Republica showcases and out-of-band credential sealed envelopes. |
| [keyring](https://github.com/jaraco/keyring) | `>=25` | MIT | Optional Extra (`[keyring]`) | Lazy access to the operating system's configured credential-store backend for resolving HMAC key references. |

---

## Development & Test Dependencies

The following tools and libraries are utilized exclusively during development, linting, packaging, and automated test execution:

| Package / Tool | Version Spec | License | Scope | Purpose |
|----------------|-------------|---------|-------|---------|
| [pytest](https://pytest.org/) | `>=7.0` | MIT | `[dev]` | Automated unit, contract, projection, and regression test execution |
| [cryptography](https://github.com/pyca/cryptography) | `>=42` | Apache-2.0 OR BSD-3-Clause | `[dev]` | Testing Republica showcase encryption and envelope workflows |
| [ruff](https://github.com/astral-sh/ruff) | `>=0.8` | MIT OR Apache-2.0 | `[dev]` | High-performance Python linter and code formatting validation |
| [tomli](https://github.com/hukkin/tomli) | `>=2.0` | MIT | `[dev]` | TOML parsing compatibility for Python < 3.11 |
| [setuptools](https://github.com/pypa/setuptools) | `>=68.0` | MIT | `[build-system]` | Standard Python packaging and build backend |
| [wheel](https://github.com/pypa/wheel) | `*` | MIT | `[build-system]` | PEP 517 wheel distribution packaging |

---

## License Texts & Attribution

### MIT License (`sqlite-transit-sync`, `keyring`, `pytest`, `ruff`, `tomli`, `setuptools`, `wheel`)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### Apache License 2.0 (`cryptography`, `ruff` dual-license option)

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

### BSD 3-Clause License (`cryptography` dual-license option)

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

### Python Software Foundation License (PSF) (Python Standard Library)

1. This LICENSE AGREEMENT is between the Python Software Foundation ("PSF"), and
   the Individual or Organization ("Licensee") accessing and otherwise using Python
   software in source or binary form and its associated documentation.

2. Subject to the terms and conditions of this License Agreement, PSF hereby
   grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
   analyze, test, perform and/or display publicly, prepare derivative works, distribute,
   and otherwise use Python alone or in any derivative version, provided, however, that
   PSF's License Agreement and PSF's notice of copyright, i.e., "Copyright (c) 2001-2026
   Python Software Foundation; All Rights Reserved" are retained in Python alone or
   in any derivative version prepared by Licensee.

---

## Security Inquiries & Contact

For questions or security disclosures regarding third-party components, consult [SECURITY.md](SECURITY.md) or contact:
- **Lead Security Coordinator:** `security@ellmos.ai`
- **Technical Maintainer:** `support@lukasgeiger.com`
- **Open-Bricks Security Team:** `security@open-bricks.org` / `lukas@open-bricks.org`
