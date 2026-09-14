# Third-Party Licenses & Software Inventory

**Project:** `sqlite-transit-sync`
**License:** [MIT License](LICENSE)
**Audit Date:** 2026-09-11
**Posture:** 100% Local-First | Zero-Egress | RunAsInvoker | 100% Permissive Licenses

---

## Runtime Architecture & Dependencies

`sqlite-transit-sync` is engineered from the ground up as a **100% local-first, zero-egress, zero-external-dependency** SQLite synchronization engine for its core push, pull, and merge operations.

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

## Governance & Runtime Invariant Alignment

The dependency footprint strictly adheres to the 10 core governance invariants:

- **INV-LOCAL-01 (100% Local-First & Zero-Egress):** Zero runtime telemetry or external network socket dependencies.
- **INV-SNAP-02 (Offline Snapshot Atomicity):** Standard library `sqlite3.backup` ensures non-locking atomic snapshot captures.
- **INV-ROLL-03 (Rollback Journal Clean Isolation):** Temporary SQLite sidecars are systematically cleaned before publication.
- **INV-PATH-04 (Strict Transit Path Containment):** Native `pathlib.Path` containment checks prevent directory traversal.
- **INV-VERIFY-05 (Two-Stage Integrity & Sanity Verification):** Cryptographic SHA-256 digests and `PRAGMA quick_check`.
- **INV-SHIELD-06 (Pre-Publication Credential Shielding):** Built-in secret detection regexes across 13+ secret families.
- **INV-HMAC-07 (HMAC Authenticity Envelope):** Standard library `hmac` and `hashlib` ensure message authenticity.
- **INV-MERGE-08 (Deterministic Row-Level Merge):** Deterministic conflict resolution with schema drift tolerance.
- **INV-RET-09 (Conservative Retention & Authority Scoping):** Owner-scoped snapshot retention garbage collection.
- **INV-SLA-10 (Non-Elevation & Multi-OS Parity):** Unprivileged user mode execution (`RunAsInvoker`) across Windows, Linux, and macOS with 48h security SLA.

---

## Security Inquiries & Contact

For questions or security disclosures regarding third-party components, consult [SECURITY.md](SECURITY.md) or contact:
- **Lead Security Coordinator:** `security@ellmos.ai`
- **Technical Maintainer:** `support@lukasgeiger.com`
- **Open-Bricks Security Team:** `security@open-bricks.org` / `lukas@open-bricks.org`
