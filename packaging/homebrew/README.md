# Homebrew tap

`brew install Hybrid3D/tap/chronon` requires a separate repository named
`Hybrid3D/homebrew-tap` (the `homebrew-` prefix is what makes `Hybrid3D/tap`
resolve). `chronon.rb` here is the source of truth; the tap holds a copy at
`Formula/chronon.rb`.

## Blocked until the PyPI release

The formula builds a virtualenv from the PyPI sdist and needs a `resource`
stanza for every transitive dependency. Both the sdist checksum and the
generated resource block come from a published release, so the tap cannot be
finished before `chronon-vcs` exists on PyPI. Everything below assumes the
`Release` workflow has published the version being packaged.

## Per-release procedure

1. Create the tap once:

   ```bash
   brew tap-new Hybrid3D/tap
   cp packaging/homebrew/chronon.rb "$(brew --repository Hybrid3D/tap)/Formula/chronon.rb"
   ```

2. Point the formula at the released sdist. Homebrew wants the hashed
   "Source" URL from the PyPI files page, not the `/packages/source/` redirect
   the placeholder uses:

   ```bash
   version=0.2.1
   python3 - "$version" <<'PY'
   import json
   import sys
   import urllib.request

   version = sys.argv[1]
   url = f"https://pypi.org/pypi/chronon-vcs/{version}/json"
   with urllib.request.urlopen(url) as response:
       data = json.load(response)
   sdist = next(f for f in data["urls"] if f["packagetype"] == "sdist")
   print(f'  url "{sdist["url"]}"')
   print(f'  sha256 "{sdist["digests"]["sha256"]}"')
   PY
   ```

   Paste both printed lines into the formula, replacing the placeholder.

3. Generate the dependency resources (rewrites the generated block in place):

   ```bash
   cd "$(brew --repository Hybrid3D/tap)"
   brew update-python-resources Formula/chronon.rb
   ```

4. Verify, then commit and push the tap:

   ```bash
   brew install --build-from-source Formula/chronon.rb
   brew test chronon
   brew audit --strict --online chronon
   ```

5. Copy the finished formula back into this repository so the two stay in sync.

`chronon-mcp` is installed into the same keg, so MCP hosts can use the absolute
path printed by `command -v chronon-mcp`.
