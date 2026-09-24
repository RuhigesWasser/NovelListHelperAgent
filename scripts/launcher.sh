#!/usr/bin/env bash
set -euo pipefail
app_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
mode=${1:-start}
shift || true
no_browser=false
if [[ ${1:-} == --no-browser ]]; then no_browser=true; shift; fi
[[ $# == 0 ]] || { echo 'Unexpected launcher argument.' >&2; exit 1; }
case "$app_root" in ''|/) echo 'Invalid application directory.' >&2; exit 1;; esac
case "$mode" in start|setup|stop|clean|login) ;; *) echo 'Expected start, setup, stop, clean or login.' >&2; exit 1;; esac
package_index='https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple'
package_fallback='https://pypi.org/simple'
python_mirror=''
uv_release_mirror='https://github.com/astral-sh/uv/releases/download'
if [[ -f "$app_root/download-sources.conf" ]]; then
  while IFS='=' read -r key value; do
    value=${value%$'\r'}
    case "$key" in PACKAGE_INDEX) package_index=$value;; PACKAGE_FALLBACK) package_fallback=$value;; PYTHON_MIRROR) python_mirror=$value;; UV_RELEASE_MIRROR) if [[ -n "$value" ]]; then uv_release_mirror=$value; fi;; esac
  done < "$app_root/download-sources.conf"
fi
system=$(uname -s)
arch=$(uname -m)
case "$system:$arch" in
  Darwin:arm64) target=aarch64-apple-darwin; digest=85f00cbdc6dd3e97eba4c31b4d014375a9fdfe8f570023b84e5102fc3456896b;;
  Darwin:x86_64) target=x86_64-apple-darwin; digest=8dcf05a8c809bb3c471d2b614788ba27a6e41298fc8c31ac84b5f4339fd468e5;;
  Linux:x86_64) target=x86_64-unknown-linux-gnu; digest=fa82fd8dde8e8eefdecada6aa0889666556cfceb690d06e0c3bca49eb3070a63;;
  Linux:aarch64|Linux:arm64) target=aarch64-unknown-linux-gnu; digest=d636d1b678e9e7f367ecb22b46bd1cabbed234d6bc3b4d96365d2b507f72f86c;;
  *) echo 'Supported: macOS or glibc Linux, x86_64 / ARM64.' >&2; exit 1;;
esac
runtime="$app_root/.runtime"
local_dir="$app_root/.local"
platform_dir="$runtime/posix/$target"
python="$platform_dir/venv/bin/python"
ready="$platform_dir/ready"

stop_app() {
  if [[ -L "$local_dir" ]]; then echo 'Refusing to access linked application data.' >&2; return 1; fi
  if [[ -x "$python" ]]; then "$python" -B "$app_root/scripts/app_control.py" stop
  elif [[ -f "$local_dir/server.lock" ]]; then
    echo 'Runtime missing: cannot verify that the application is stopped. Restore its runtime before cleaning.' >&2; return 1
  fi
}
if [[ $mode == stop ]]; then stop_app; exit; fi
if [[ $mode == clean ]]; then
  printf 'Remove runtime, saved accounts, tasks and ALL books inside %s?\nType CLEAN to continue: ' "$app_root"
  IFS= read -r answer || answer=''
  [[ $answer == CLEAN ]] || { echo 'Cancelled.'; exit 0; }
  if [[ ! -L "$runtime" && ! -L "$local_dir" ]]; then stop_app; fi
  for relative in .runtime .local .agents/.venv-ocr; do
    # Never traverse a linked .agents parent; rm unlinks child symlinks itself.
    if [[ $relative == .agents/* && -L "$app_root/.agents" ]]; then continue; fi
    remove_path="$app_root/$relative"
    case "$remove_path" in "$app_root/.runtime"|"$app_root/.local"|"$app_root/.agents/.venv-ocr") rm -rf -- "$remove_path";; *) exit 1;; esac
  done
  echo 'Local application data removed. Source files and external exports remain.'
  exit
fi
if [[ $mode == login ]]; then
  [[ -x "$python" ]] || { echo 'Run Start.sh first.' >&2; exit 1; }
  exec "$python" -B -X utf8 "$app_root/scripts/esj_login.py"
fi
for path in "$runtime" "$local_dir" "$runtime/posix" "$platform_dir" "$platform_dir/venv" "$platform_dir/python" "$platform_dir/uv" "$runtime/cache" "$local_dir/tmp" "$local_dir/logs"; do
  [[ ! -L "$path" ]] || { echo "Application directories must not be symlinks: $path" >&2; exit 1; }
done
open_browser() {
  if $no_browser; then return; fi
  if [[ $system == Darwin ]]; then open "$1"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  else printf 'Open this address in your browser: %s\n' "$1"; fi
}
if [[ -x "$python" && $mode == start ]]; then
  if address=$("$python" -B "$app_root/scripts/app_control.py" status); then open_browser "$address"; echo "Ready: $address"; exit; fi
fi
file_hash() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d ' ' -f1
  else shasum -a 256 "$1" | cut -d ' ' -f1; fi
}
[[ -f "$app_root/uv.lock" && -f "$app_root/pyproject.toml" ]] || { echo 'Download the complete project, including uv.lock.' >&2; exit 1; }
fingerprint="$(file_hash "$app_root/uv.lock")-$(file_hash "$app_root/pyproject.toml")"
expected=$(printf '%s\n%s' "$app_root" "$fingerprint")
needs_setup=true
if [[ -x "$python" && -f "$ready" && $(cat "$ready") == "$expected" ]]; then needs_setup=false; fi
if $needs_setup; then
  printf 'Install/update private Python 3.12 and packages inside %s?\nBundled runtime is preferred; package sources are set in download-sources.conf. No sudo, global Python, shell profile or PATH changes.\nAllow local installation? [y/N] ' "$runtime"
  IFS= read -r answer || answer=''
  case "$answer" in y|Y|yes|YES) ;; *) echo 'Cancelled. Nothing installed.'; exit 0;; esac
fi
umask 077
mkdir -p "$platform_dir" "$local_dir/tmp" "$local_dir/logs"
export UV_CACHE_DIR="$runtime/cache/uv" UV_PYTHON_CACHE_DIR="$runtime/cache/python"
export UV_PYTHON_INSTALL_DIR="$platform_dir/python" UV_PYTHON_BIN_DIR="$platform_dir/bin"
export UV_TOOL_DIR="$platform_dir/tools" UV_TOOL_BIN_DIR="$platform_dir/bin"
export UV_PROJECT_ENVIRONMENT="$platform_dir/venv" UV_PYTHON_INSTALL_BIN=false UV_NO_MODIFY_PATH=true
export UV_NO_CONFIG=true UV_NO_PROGRESS=true UV_NO_ENV_FILE=true
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONUTF8=1
export TEMP="$local_dir/tmp" TMP="$local_dir/tmp" TMPDIR="$local_dir/tmp"
export PIP_CACHE_DIR="$runtime/cache/pip" XDG_CACHE_HOME="$runtime/cache" XDG_CONFIG_HOME="$local_dir/config"
export XDG_DATA_HOME="$local_dir/data" HF_HOME="$runtime/cache/huggingface" MPLCONFIGDIR="$runtime/cache/matplotlib"
if $needs_setup; then
  uv="$platform_dir/uv/uv"
  if [[ -x "$app_root/vendor/uv/uv" ]]; then uv="$app_root/vendor/uv/uv"; fi
  if [[ ! -x "$uv" ]]; then
    archive="$platform_dir/uv.tar.gz"
    url="${uv_release_mirror%/}/0.12.17/uv-$target.tar.gz"
    curl --disable --fail --location --retry 2 --noproxy '*' "$url" --output "$archive" || curl --disable --fail --location --retry 2 "$url" --output "$archive"
    [[ $(file_hash "$archive") == "$digest" ]] || { echo 'uv checksum mismatch.' >&2; exit 1; }
    mkdir -p "$platform_dir/uv"
    tar -xzf "$archive" --strip-components=1 -C "$platform_dir/uv"
    rm -f -- "$archive"
  fi
  if [[ -x "$python" ]] && "$python" -B "$app_root/scripts/app_control.py" status >/dev/null 2>&1; then echo "Stop the application before updating its environment." >&2; exit 1; fi
  if [[ -d "$platform_dir/venv" ]]; then rm -rf -- "$platform_dir/venv"; fi
  cd "$app_root"
  if [[ -n "$python_mirror" ]]; then export UV_PYTHON_INSTALL_MIRROR="$python_mirror"; fi
  if [[ -x "$app_root/vendor/python/bin/python3" ]]; then
    export UV_PYTHON="$app_root/vendor/python/bin/python3" UV_PYTHON_DOWNLOADS=never
    "$uv" venv --python "$UV_PYTHON" "$platform_dir/venv"
  else
    "$uv" venv --managed-python --python 3.12 "$platform_dir/venv"
  fi
  requirements="$platform_dir/requirements.lock.txt"
  "$uv" export --locked --no-dev --no-emit-project --format requirements-txt --output-file "$requirements" --quiet >/dev/null
  installed=false
  for index in "$package_index" "$package_fallback"; do
    [[ -n "$index" ]] || continue
    echo "Installing locked packages from: $index"
    if (unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; export NO_PROXY='*' no_proxy='*'; "$uv" pip sync --python "$python" --require-hashes --only-binary :all: --index-url "$index" "$requirements"); then installed=true; break; fi
    if [[ -n ${HTTP_PROXY:-}${HTTPS_PROXY:-}${ALL_PROXY:-}${http_proxy:-}${https_proxy:-}${all_proxy:-} ]]; then
      if "$uv" pip sync --python "$python" --require-hashes --only-binary :all: --index-url "$index" "$requirements"; then installed=true; break; fi
    fi
  done
  $installed || { echo 'Dependency setup failed. Check download-sources.conf.' >&2; exit 1; }
  check_code='import cv2, onnxruntime, aiotieba'
  if [[ -f "$app_root/app/server.py" ]]; then check_code+='; import app.server'; fi
  if ! "$python" -B -c "$check_code"; then
    echo 'Runtime import failed. On minimal Linux, check libGL and glib system libraries. See docs/USAGE.md.' >&2; exit 1
  fi
  printf '%s\n' "$expected" > "$ready"
fi
if [[ $mode == setup ]]; then echo 'Local environment ready.'; exit; fi
cd "$app_root"
# Opening the browser in the launcher also works when this is a second instance.
nohup "$python" -B -m app.main --no-browser >"$local_dir/logs/server.out.log" 2>"$local_dir/logs/server.err.log" < /dev/null &
app_pid=$!
attempt=0
while [[ $attempt -lt 120 ]]; do
  if address=$("$python" -B "$app_root/scripts/app_control.py" status); then open_browser "$address"; echo "Ready: $address"; exit; fi
  kill -0 "$app_pid" 2>/dev/null || break
  sleep .25
  attempt=$((attempt+1))
done
echo "Startup failed. See $local_dir/logs/server.err.log" >&2
exit 1
