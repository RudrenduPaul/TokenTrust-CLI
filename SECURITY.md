# Security Policy

TokenTrust ships two distributions: an npm package (`tokentrust-cli`, TypeScript) and a PyPI
package (`tokentrust-cli`, Python). This policy applies to both.

## Supported Versions

TokenTrust is currently in v0.x (pre-1.0). Security fixes are applied to the
latest published `0.x` release on npm and the latest published version on PyPI.
There is no long-term-support branch yet at this stage of the project.

| Version | npm | PyPI |
| ------- | --- | ---- |
| 0.3.x   | :white_check_mark: | :white_check_mark: |
| < 0.3   | :x: | n/a |

## Reporting a Vulnerability

If you find a security vulnerability in TokenTrust, please report it privately
rather than opening a public GitHub issue.

- **Report privately via:** [GitHub Security Advisories](https://github.com/RudrenduPaul/TokenTrust-CLI/security/advisories/new)
- **Response time:** we aim to acknowledge every report within **48 hours**.
- **Disclosure:** please give us a reasonable window to investigate and ship a
  fix before any public disclosure. We will credit reporters (unless you ask
  to stay anonymous) once a fix is released.

When reporting, please include:

1. A description of the vulnerability and its potential impact.
2. Steps to reproduce (a minimal repro is ideal — TokenTrust ships a fixture
   corpus under `fixtures/` and `src/categories/testdata/` you can use as a
   base).
3. The TokenTrust version, and either the Node.js version (npm package) or
   the Python version (PyPI package) you're running.
4. Any proxy adapter involved (`rtk`, `headroom`), if relevant —
   for example, a vulnerability triggered by a proxy's output reaching the
   tokenizer or the report writer.

## Scope

TokenTrust shells out to external proxy binaries (`rtk`, `headroom`) as
unprivileged child processes, using `child_process.spawn` (npm package) or
`subprocess.run` (PyPI package), neither via a shell. It never sends task
content, repo data, or measurement results to any third party unless you
explicitly opt into `--live` mode with your own API key. Security reports
involving credential handling, command injection through task/fixture
input, or JSON report parsing are especially high priority. The PyPI
package's tokenizer dependency (`tiktoken`) fetches public, non-sensitive
`cl100k_base` rank data from OpenAI's servers on first use in a fresh
environment (see `python/docs/getting-started.md`). That is the one
network call the Python package makes outside of `--live` mode, and it
carries no user data.

Vulnerabilities in the third-party proxy binaries themselves (`rtk`,
`headroom`) are out of scope for this repository — please report those
directly to the respective project.

## Our Commitment

We run `npm audit --audit-level=high` on every pull request touching the npm package, and do not
ship a release with an unfixed HIGH or CRITICAL severity CVE in either package's dependency
tree. The PyPI package pins its dependencies to bounded version ranges
(`tiktoken>=0.7,<1`, `PyYAML>=6.0,<7`) in `python/pyproject.toml`.
