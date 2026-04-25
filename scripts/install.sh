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
README_URL="${LETSVIBEDESIGN_README_URL:-https://github.com/kmeanskaran/desysflow-oss#readme}"
DOCS_URL="${LETSVIBEDESIGN_DOCS_URL:-https://github.com/kmeanskaran/desysflow-oss/tree/main/docs}"
GETTING_STARTED_URL="${LETSVIBEDESIGN_GETTING_STARTED_URL:-https://github.com/kmeanskaran/desysflow-oss/blob/main/docs/getting-started.md}"
BRAND="desysflow🌀"
LOG_DIR="${TMPDIR:-/tmp}"
INSTALL_LOG=""
PLATFORM=""
RC_FILE=""

print_header() {
  printf '%s install\n' "$BRAND"
}

log() {
  printf '> %s\n' "$1"
}

warn() {
  printf '> warning: %s\n' "$1" >&2
}

die() {
  printf '> error: %s\n' "$1" >&2
  if [ -n "${INSTALL_LOG:-}" ] && [ -f "$INSTALL_LOG" ]; then
    printf '> log: %s\n' "$INSTALL_LOG" >&2
  fi
  exit 1
}

run_logged() {
  local label="$1"
  shift
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$label" >> "$INSTALL_LOG"
  if ! "$@" >> "$INSTALL_LOG" 2>&1; then
    warn "$label failed"
    tail -n 40 "$INSTALL_LOG" >&2 || true
    return 1
  fi
}

prepare_log_file() {
  mkdir -p "$LOG_DIR"
  INSTALL_LOG="$(mktemp "${LOG_DIR%/}/desysflow-install.XXXXXX")"
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
    *) die "unsupported platform: $kernel" ;;
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
    log "installing required packages with Homebrew"
    run_logged "brew install git node" brew install git node
    log "required packages installed"
    return
  fi

  if has_cmd apt-get; then
    log "installing required packages with apt"
    run_logged "sudo apt-get update" sudo apt-get update
    run_logged "sudo apt-get install -y curl git nodejs npm" sudo apt-get install -y curl git nodejs npm
    log "required packages installed"
    return
  fi

  if has_cmd dnf; then
    log "installing required packages with dnf"
    run_logged "sudo dnf install -y curl git nodejs npm" sudo dnf install -y curl git nodejs npm
    log "required packages installed"
    return
  fi

  if has_cmd pacman; then
    log "installing required packages with pacman"
    run_logged "sudo pacman -Sy --noconfirm curl git nodejs npm" sudo pacman -Sy --noconfirm curl git nodejs npm
    log "required packages installed"
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

  log "installing uv"
  run_logged "Installing uv via Astral installer" sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'

  if [ -x "$HOME/.local/bin/uv" ]; then
    PATH="$HOME/.local/bin:$PATH"
    export PATH
  fi

  has_cmd uv || die "uv installation completed but uv is still not on PATH"
  log "uv ready"
}

install_repo() {
  mkdir -p "$INSTALL_HOME"

  if [ -n "$LOCAL_REPO" ]; then
    LOCAL_REPO="$(cd "$LOCAL_REPO" && pwd)"
    [ -f "$LOCAL_REPO/letsvibedesign" ] || die "LETSVIBEDESIGN_LOCAL_REPO does not look like a desysflow checkout: $LOCAL_REPO"
    REPO_DIR="$LOCAL_REPO"
    log "using local repository: $REPO_DIR"
    return
  fi

  if [ -d "$REPO_DIR/.git" ]; then
    if is_true "$OFFLINE"; then
      log "using existing offline installation: $REPO_DIR"
      return
    fi
    log "cleaning generated runtime directories for legacy ui -> studio migration"
    rm -rf \
      "$REPO_DIR/.venv" \
      "$REPO_DIR/studio/.vite" \
      "$REPO_DIR/studio/node_modules" \
      "$REPO_DIR/studio/dist" \
      "$REPO_DIR/ui/.vite" \
      "$REPO_DIR/ui/node_modules" \
      "$REPO_DIR/ui/dist"
    log "updating repository"
    run_logged "git fetch origin $REPO_REF --depth 1" git -C "$REPO_DIR" fetch origin "$REPO_REF" --depth 1
    run_logged "git checkout -B $REPO_REF origin/$REPO_REF" git -C "$REPO_DIR" checkout -B "$REPO_REF" "origin/$REPO_REF"
    log "repository updated"
    return
  fi

  if [ -e "$REPO_DIR" ]; then
    die "install path exists and is not a git repository: $REPO_DIR"
  fi

  if is_true "$OFFLINE"; then
    die "offline mode requires an existing install at $REPO_DIR or LETSVIBEDESIGN_LOCAL_REPO to be set"
  fi

  log "cloning repository"
  run_logged "git clone --depth 1 --branch $REPO_REF $REPO_URL $REPO_DIR" git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR"
  log "repository ready"
}

bootstrap_repo() {
  log "bootstrapping runtime"
  run_logged "bootstrap.sh" env \
    REPO_DIR="$REPO_DIR" \
    DESYSFLOW_BOOTSTRAP_PYTHON="${DESYSFLOW_BOOTSTRAP_PYTHON:-3.11}" \
    bash -c '
      cd "$REPO_DIR"
      DESYSFLOW_BOOTSTRAP_NON_INTERACTIVE=1 \
      DESYSFLOW_SKIP_MODEL_CHECK=1 \
      DESYSFLOW_BOOTSTRAP_PYTHON="$DESYSFLOW_BOOTSTRAP_PYTHON" \
      ./scripts/bootstrap.sh
    '
  log "runtime ready"
}

install_launcher() {
  log "installing launcher"
  mkdir -p "$BIN_DIR"
  cat > "$LAUNCHER_PATH" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$REPO_DIR/letsvibedesign" "\$@"
EOF
  chmod +x "$LAUNCHER_PATH"
  log "launcher installed: $LAUNCHER_PATH"
}

shell_rc_path() {
  case "$PLATFORM:${SHELL:-}" in
    macos:*/zsh)
      printf '%s\n' "$HOME/.zshrc"
      ;;
    macos:*/bash)
      if [ -f "$HOME/.bash_profile" ]; then
        printf '%s\n' "$HOME/.bash_profile"
      else
        printf '%s\n' "$HOME/.bashrc"
      fi
      ;;
    macos:*)
      printf '%s\n' "$HOME/.zshrc"
      ;;
    linux:*/zsh|wsl2:*/zsh)
      printf '%s\n' "$HOME/.zshrc"
      ;;
    linux:*|wsl2:*)
      printf '%s\n' "$HOME/.bashrc"
      ;;
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
  local path_dir path_line
  RC_FILE="$(shell_rc_path)"
  path_dir="$BIN_DIR"
  if [ "$path_dir" = "$HOME/.local/bin" ]; then
    path_line='export PATH="$HOME/.local/bin:$PATH"'
  else
    path_line="export PATH=\"$path_dir:\$PATH\""
  fi

  mkdir -p "$(dirname "$RC_FILE")"
  touch "$RC_FILE"

  if ! grep -Fqx "$path_line" "$RC_FILE"; then
    log "adding $BIN_DIR to PATH in $RC_FILE"
    {
      printf '\n# letsvibedesign\n'
      printf '%s\n' "$path_line"
    } >> "$RC_FILE"
  else
    log "PATH already includes $BIN_DIR in $RC_FILE"
  fi
}

print_next_steps() {
  printf '\n%s installed\n' "$BRAND"
  printf '> platform: %s\n' "$PLATFORM"
  printf '> repo: %s\n' "$REPO_DIR"
  printf '> launcher: %s\n' "$LAUNCHER_PATH"
  printf '> shell rc: %s\n' "$RC_FILE"
  printf '> run: source "%s" && letsvibedesign\n' "$RC_FILE"
  printf '> readme: %s\n' "$README_URL"
  printf '> docs: %s\n' "$DOCS_URL"
  printf '> getting started: %s\n' "$GETTING_STARTED_URL"
  printf '> config: %s/.env.example\n' "$REPO_DIR"
  printf '> install log: %s\n' "$INSTALL_LOG"
}

main() {
  prepare_log_file
  detect_platform
  print_header
  log "platform: $PLATFORM"
  ensure_system_deps
  ensure_uv
  install_repo
  bootstrap_repo
  install_launcher
  ensure_path_export
  print_next_steps
}

main "$@"
