# Python dependency locks

Each deployable Python service keeps `requirements.txt` as its
human-maintained list of direct dependencies. The adjacent
`requirements.lock.txt` is generated: it contains the exact transitive graph
and package hashes and must never be edited by hand.

Developers edit `requirements.txt` and regenerate the adjacent lock after an
intentional dependency change. Repository Dockerfiles and CI install only the
generated lock with `--require-hashes`; they do not resolve the direct
requirements independently. Never install both files into one environment.
CI regenerates all four locks with the same script and fails if the generated
files differ from the committed locks; regeneration never commits changes.

## Generation environments

Run generation on Linux with Docker using:

```text
./scripts/compile_python_locks.sh
```

The script pins both image digests, the compilation resolver at `pip==25.0.1`,
and `pip-tools==7.5.1`. The base-image pip versions are recorded below, but
both graphs are compiled through the pinned pip 25.0.1 tool environment:

| Graph | Compilation image | Python | pip |
|---|---|---:|---:|
| API | `python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea` | 3.12.14 | 25.0.1 |
| worker / beat | same as API | 3.12.14 | 25.0.1 |
| Yuyu collector | `mcr.microsoft.com/playwright/python:v1.61.0-jammy@sha256:108b33fc1c785c056665b04c320a612526503b0b081209eea2e1ec89e3b69a8f` | 3.10.12 | 26.1.2 |
| SNKRDUNK collector | same as Yuyu | 3.10.12 | 26.1.2 |

The collector image's Python 3.10 runtime is intentional here: it is the
repository's current deployment image. Generating a Python 3.12-only collector
lock would produce packages that the deployed image cannot install. Aligning
all service base runtimes is a separate Docker/runtime decision for M4C, not a
dependency change to hide in lock generation.

## Shared constraints

`constraints/python-shared.txt` aligns only compatibility-sensitive packages:

- SQLAlchemy, psycopg, Pydantic, and pydantic-settings across database users
- Celery and Redis between the API producer and worker/beat consumers
- Beautiful Soup across parsers
- Pillow, ImageHash, and NumPy across image-analysis users

Constraints do not install packages and are not a replacement for a service's
direct requirements. NumPy has a documented Python-version marker because the
current Playwright Jammy/Python 3.10 image cannot install the proven Python
3.12 NumPy 2.5 line.

## Upgrade rule

Regenerate all four locks together and review their diff. Dependency upgrades
must be an intentional, separately tested change; do not combine an upgrade
with the initial adoption of locks. Never manually edit generated transitive
versions or hashes.
