#!/usr/bin/env bash

set -euo pipefail

REPO_URL="${LETSVIBEDESIGN_REPO_URL:-https://github.com/kmeanskaran/desysflow-oss.git}"
REPO_REF="${LETSVIBEDESIGN_REPO_REF:-main}"
INSTALL_HOME="${LETSVIBEDESIGN_HOME:-$HOME/.letsvibedesign}"
REPO_DIR="${LETSVIBEDESIGN_REPO_DIR:-$INSTALL_HOME/desysflow-oss}"
LOCAL_REPO="${LETSVIBEDESIGN_LOCAL_REPO:-}"
BIN_DIR="${LETSVIBEDESIGN_BIN_DIR:-$HOME/.local/bin}"
LAUNCHER_PATH="$BIN_DIR/letsvibedesign"
OFFLINE="${LETSVIBEDESIGN_OFFLINE:-0}"

log() {
  printf '[install] %s\n' "$1"
}

warn() {
  printf '[install] warning: %s\n' "$1" >&2
}

die() {
  printf '[install] error: %s\n' "$1" >&2
  exit 1
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

detect_platform() {
  local kernel
  kernel="$(uname -s)"
  case "$kernel" in
    Darwin) PLATFORM="macos" ;;
    Linux) PLATFORM="linux" ;;
    *)
      die "unsupported platform: $kernel"
      ;;
  esac

  if [ "$PLATFORM" = "linux" ] && grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null; then
    PLATFORM="wsl2"
  fi
}

ensure_system_deps() {
  local missing=0

  for cmd in curl git; do
    if ! has_cmd "$cmd"; then
      warn "missing required command: $cmd"
      missing=1
    fi
  done

  if ! has_cmd node; then
    warn "missing required command: node"
    missing=1
  fi

  if ! has_cmd npm; then
    warn "missing required command: npm"
    missing=1
  fi

  if [ "$missing" -eq 0 ]; then
    return
  fi

  if [ "$PLATFORM" = "macos" ]; then
    if ! has_cmd brew; then
      die "Homebrew is required to auto-install dependencies on macOS. Install brew, then rerun this script."
    fi
    log "Installing missing system packages with Homebrew"
    brew install git node
    return
  fi

  if has_cmd apt-get; then
    log "Installing missing system packages with apt"
    sudo apt-get update
    sudo apt-get install -y curl git nodejs npm
    return
  fi

  if has_cmd dnf; then
    log "Installing missing system packages with dnf"
    sudo dnf install -y curl git nodejs npm
    return
  fi

  if has_cmd pacman; then
    log "Installing missing system packages with pacman"
    sudo pacman -Sy --noconfirm curl git nodejs npm
    return
  fi

  die "could not install system dependencies automatically. Install curl, git, node, and npm, then rerun."
}

ensure_uv() {
  if has_cmd uv; then
    return
  fi

  if is_true "$OFFLINE"; then
    die "uv is required in offline mode. Install uv first, then rerun."
  fi

  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh

  if [ -x "$HOME/.local/bin/uv" ]; then
    PATH="$HOME/.local/bin:$PATH"
    export PATH
  fi

  has_cmd uv || die "uv installation completed but uv is still not on PATH"
}

install_repo() {
  mkdir -p "$INSTALL_HOME"

  if [ -n "$LOCAL_REPO" ]; then
    LOCAL_REPO="$(cd "$LOCAL_REPO" && pwd)"
    [ -f "$LOCAL_REPO/letsvibedesign" ] || die "LETSVIBEDESIGN_LOCAL_REPO does not look like a desysflow checkout: $LOCAL_REPO"
    REPO_DIR="$LOCAL_REPO"
    log "Using local repository at $REPO_DIR"
    return
  fi

  if [ -d "$REPO_DIR/.git" ]; then
    if is_true "$OFFLINE"; then
      log "Using existing installation in offline mode at $REPO_DIR"
      return
    fi
    log "Updating existing installation in $REPO_DIR"
    git -C "$REPO_DIR" fetch origin "$REPO_REF" --depth 1
    git -C "$REPO_DIR" checkout -B "$REPO_REF" "origin/$REPO_REF"
    return
  fi

  if [ -e "$REPO_DIR" ]; then
    die "install path exists and is not a git repository: $REPO_DIR"
  fi

  if is_true "$OFFLINE"; then
    die "offline mode requires an existing install at $REPO_DIR or LETSVIBEDESIGN_LOCAL_REPO to be set"
  fi

  log "Cloning repository into $REPO_DIR"
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR"
}

bootstrap_repo() {
  log "Bootstrapping Python environment and UI dependencies"
  (
    cd "$REPO_DIR"
    DESYSFLOW_BOOTSTRAP_NON_INTERACTIVE=1 \
    DESYSFLOW_SKIP_MODEL_CHECK=1 \
    DESYSFLOW_BOOTSTRAP_PYTHON="${DESYSFLOW_BOOTSTRAP_PYTHON:-3.11}" \
    ./scripts/bootstrap.sh
  )
}

install_launcher() {
  log "Installing letsvibedesign launcher to $LAUNCHER_PATH"
  mkdir -p "$BIN_DIR"
  cat > "$LAUNCHER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$REPO_DIR/letsvibedesign" "\$@"
EOF
  chmod +x "$LAUNCHER_PATH"
}

shell_rc_path() {
  case "${SHELL:-}" in
    */zsh)
      printf '%s\n' "$HOME/.zshrc"
      ;;
    */bash)
      if [ -f "$HOME/.bashrc" ]; then
        printf '%s\n' "$HOME/.bashrc"
      else
        printf '%s\n' "$HOME/.bash_profile"
      fi
      ;;
    *)
      if [ -f "$HOME/.zshrc" ]; then
        printf '%s\n' "$HOME/.zshrc"
      else
        printf '%s\n' "$HOME/.bashrc"
      fi
      ;;
  esac
}

ensure_path_export() {
  local path_dir path_line rc_file
  rc_file="$(shell_rc_path)"
  path_dir="$BIN_DIR"
  if [ "$path_dir" = "$HOME/.local/bin" ]; then
    path_line='export PATH="$HOME/.local/bin:$PATH"'
  else
    path_line="export PATH=\"$path_dir:\$PATH\""
  fi

  mkdir -p "$(dirname "$rc_file")"
  touch "$rc_file"

  if ! grep -Fqx "$path_line" "$rc_file"; then
    log "Adding $BIN_DIR to PATH in $rc_file"
    {
      printf '\n# letsvibedesign\n'
      printf '%s\n' "$path_line"
    } >> "$rc_file"
  fi
}

print_next_steps() {
  local rc_file
  rc_file="$(shell_rc_path)"

  cat <<EOF

letsvibedesign is installed.

Next:
  source "$rc_file"
  letsvibedesign

Notes:
  - Installer target: $PLATFORM
  - Repo location: $REPO_DIR
  - Offline mode: $OFFLINE
  - First launch uses the default local Ollama config written to .env.example.
  - If you want OpenAI or Anthropic, edit $REPO_DIR/.env.example or rerun ./scripts/bootstrap.sh there.
EOF
}

main() {
  detect_platform
  log "Detected platform: $PLATFORM"
  ensure_system_deps
  ensure_uv
  install_repo
  bootstrap_repo
  install_launcher
  ensure_path_export
  print_next_steps
}

main "$@"
