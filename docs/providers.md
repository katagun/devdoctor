# Provider catalogue

Providers are the scanners: each one knows where one family of disk usage
lives, how big it is, and what cleanup is safe. `devdoctor providers` shows
what is registered and available on *your* machine.

Risk levels: **safe** (regenerable caches — delete freely),
**reclaimable** (rebuildable at a cost in time or bandwidth — confirm each),
**dangerous** (may hold user data — skipped unless `--allow-dangerous`).
Mixed providers carry entries at more than one level; the per-entry label
always wins.

## Built-in providers

| Provider | Covers | Risk |
|---|---|---|
| `uv-cache`, `pip-cache`, `poetry-cache` | Python package download caches (`uv-cache` asks `uv cache dir` where the cache is, and forces past the lock a parent `uv run` holds) | safe |
| `npm-cache`, `pnpm-store`, `bun-cache` | JS package-manager stores | safe |
| `yarn-cache` | Yarn cache (project-local Zero-Install caches are dangerous advice instead) | safe / dangerous |
| `cargo-dependency-cache` | Cargo registry archives, sources, git checkouts | reclaimable |
| `go-caches` | Go build, test, fuzz, and module caches | safe |
| `nuget-caches` | NuGet global packages, HTTP, temp, plugin caches | safe |
| `conda-package-caches` | Conda package caches | reclaimable |
| `homebrew-downloads` | Cached Homebrew bottles | safe |
| `vscode-extension-downloads`, `cursor-extension-downloads`, `cursor-updater-cache`, `vscode-logs`, `cursor-logs` | Editor extension package downloads, Cursor's staged updates, session logs | safe |
| `pre-commit-cache`, `puppeteer-browsers`, `node-gyp-cache`, `electron-cache`, `opam-download-cache`, `google-updater-cache` | Tool download caches: hook environments, browsers, Node headers, Electron binaries, opam sources, updater downloads | safe |
| `gradle-caches` | JVM build caches | safe |
| `maven-repo` | Local Maven repository (re-downloadable artifacts) | reclaimable |
| `chrome-cache`, `firefox-cache`, `arc-browser-cache`, `vscode-cache`, `cursor-cache` | Browser and editor caches | safe |
| `slack-service-worker` | Slack cached web assets | reclaimable |
| `tiktoken-cache` | Tokenizer cache | safe |
| `nltk-data`, `spacy-cache`, `wandb-cache`, `sentence-transformers-cache`, `torch-hub-cache`, `flair-cache`, `llama-cpp-cache`, `modelscope-cache`, `helix-cache` | ML/NLP datasets and model caches | reclaimable |
| `docker` | Images, containers, and unused volumes (named volumes: dangerous; anonymous: reclaimable) | reclaimable / dangerous |
| `docker-vm-disk` | The Docker Desktop VM disk file itself | reclaimable |
| `colima-vm-disk` | Colima (Lima) VM disk images; advice only, since deleting one destroys the VM's containers and volumes | reclaimable |
| `colima-cache` | Colima's downloaded VM base images | safe |
| `rustup-toolchains`, `nvm-node-versions`, `pyenv-versions` | Installed toolchains and language versions, one entry each; advice names the tool's own uninstall command, since one may be in use and a bare delete leaves the tool's index stale | reclaimable |
| `vagrant-boxes`, `steampipe-plugins`, `docling-cache` | Downloaded boxes and plugins (advice: `vagrant box prune`, `steampipe plugin uninstall`) and Docling models | reclaimable |
| `editor-extensions` | Installed VS Code, Cursor and Windsurf extensions; advice names the editor's uninstall command | reclaimable |
| `codex-runtimes-cache`, `exo-models` | Codex CLI downloaded runtimes, exo model weights | reclaimable |
| `git-worktrees` | Linked worktrees whose branches are fully integrated (anything else: advice) | reclaimable |
| `time-machine-local-snapshots` (macOS only) | Local snapshots; one all-but-newest bundle plus per-snapshot entries | reclaimable |
| `node-project-dependencies` | `node_modules` under common code roots | reclaimable |
| `cargo-targets` | Cargo workspace `target/` build dirs | reclaimable |
| `python-venvs` | Virtualenvs (rebuildable with `uv sync` / `pip install -r`) | reclaimable |
| `tox-nox-environments` | Generated tox/nox test environments | safe |
| `conda-environments` | Non-base Conda environments (may hold your work) | dangerous |
| `xcode-development-data` (macOS only) | Derived data, device support, archives, unavailable simulators | reclaimable |
| `android-sdk-storage`, `android-project-builds` | SDK system images, emulator storage, Gradle build dirs | reclaimable |
| `ollama`, `huggingface-hub`, `lm-studio-models`, `gpt4all-models`, `jan-models`, `msty-models`, and other `*-models` / `*-cache` AI providers | Local model weights and inference caches | reclaimable |
| `large-files` | Unusually large files anywhere scanned — user data until you say otherwise | dangerous |
| `downloads` | `~/Downloads` | dangerous |

Project discovery (`node-project-dependencies`, `cargo-targets`,
`git-worktrees`, `android-project-builds`) is bounded to common code roots
or the colon-separated paths in `DEVDOCTOR_PROJECT_ROOTS`.

## Platform notes

- `time-machine-local-snapshots` and `xcode-development-data` need macOS
  (`tmutil`, Xcode paths). Everywhere else, providers run on macOS and Linux.
- Providers report *unavailability* instead of failing: a missing binary or a
  wrong platform shows up in `devdoctor providers` and in the report's
  `diagnostics`, never as a crash.
- Entries DevDoctor cannot measure (e.g. snapshot sizes macOS does not
  disclose) are still offered with unknown size rather than hidden.

## Adding coverage

New coverage lands as a provider with a name, a family, a risk, and an
availability check — see `src/devdoctor/providers/` and
`src/devdoctor/data/paths.yaml`. When you add one, add its row to this
table.
