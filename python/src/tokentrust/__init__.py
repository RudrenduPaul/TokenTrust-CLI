"""
TokenTrust: vendor-neutral CLI that independently verifies the actual
token/cost savings delivered by AI-coding-agent context-reduction proxies
(rtk, headroom) against a real, labeled task corpus and a local tokenizer.

This is the Python port of the npm package `tokentrust-cli`
(https://www.npmjs.com/package/tokentrust-cli). Same CLI surface, same
verification categories (TT01-TT05), same bundled task corpus, same
cl100k_base local tokenizer -- ported from the TypeScript source at
https://github.com/RudrenduPaul/TokenTrust-CLI so teams that already run a
Python toolchain can `pip install tokentrust-cli` instead of pulling in
Node.js.
"""

from __future__ import annotations

from importlib import metadata as _importlib_metadata

try:
    # Read the version from the installed package's own metadata rather
    # than a hand-maintained string here, which had silently drifted from
    # the real pyproject.toml version -- this constant was still "0.2.0"
    # while the package had shipped 0.3.1 on PyPI, so
    # `import tokentrust; tokentrust.__version__` reported a stale, wrong
    # version to any caller importing the module.
    __version__ = _importlib_metadata.version("tokentrust-cli")
except _importlib_metadata.PackageNotFoundError:
    # Not installed (e.g. running straight from a source checkout without
    # `pip install -e .`) -- fall back to a clearly-labeled placeholder
    # instead of a number that can silently go stale again.
    __version__ = "0.0.0-dev"

__all__ = ["__version__"]
