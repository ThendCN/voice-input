#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

INSTALL_DIR="$HOME/voice-input"
REPO_URL="https://github.com/ThendCN/voice-input.git"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
VAD_URL="https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"

echo "========================================="
echo "  voice-input 离线语音输入法 安装脚本"
echo "========================================="
echo ""

# --- 检查基本工具 ---
command -v git >/dev/null || error "需要 git"
command -v uv >/dev/null || error "需要 uv (https://docs.astral.sh/uv/)"

# --- 检测包管理器 ---
if command -v pacman >/dev/null; then
    PKG_MGR="pacman"
elif command -v apt >/dev/null; then
    PKG_MGR="apt"
else
    error "仅支持 Arch Linux (pacman) 和 Debian/Ubuntu (apt)"
fi

# --- 安装系统依赖 ---
echo ""
info "安装系统依赖..."
if [ "$PKG_MGR" = "pacman" ]; then
    sudo pacman -S --needed --noconfirm keyd ydotool wl-clipboard
else
    sudo apt install -y keyd ydotool wl-clipboard libnotify-bin
fi

# --- 用户加入 input 组 ---
if ! groups | grep -q '\binput\b'; then
    info "将用户加入 input 组..."
    sudo usermod -aG input "$USER"
    warn "input 组权限需要重新登录后生效"
    NEED_RELOGIN=1
else
    NEED_RELOGIN=0
fi

# --- 配置 keyd ---
info "配置 keyd (Caps Lock → F13)..."
if [ -f /etc/keyd/default.conf ]; then
    if grep -q "capslock = f13" /etc/keyd/default.conf; then
        info "keyd 已配置，跳过"
    else
        warn "/etc/keyd/default.conf 已存在，请手动添加: capslock = f13"
    fi
else
    sudo tee /etc/keyd/default.conf > /dev/null << 'KEYDEOF'
[ids]
*

[main]
capslock = f13
KEYDEOF
fi
sudo systemctl enable --now keyd
sudo keyd reload 2>/dev/null || true

# --- 克隆/更新项目 ---
if [ -d "$INSTALL_DIR/.git" ]; then
    info "更新项目..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "克隆项目到 $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# --- Python 依赖 ---
info "安装 Python 依赖..."
uv sync

# --- 下载模型 ---
mkdir -p models
SENSEVOICE_DIR="models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
if [ -f "$SENSEVOICE_DIR/model.int8.onnx" ]; then
    info "SenseVoice 模型已存在，跳过"
else
    info "下载 SenseVoice 模型 (~156MB)..."
    wget -q --show-progress -O models/sensevoice.tar.bz2 "$MODEL_URL"
    tar xf models/sensevoice.tar.bz2 -C models/
    rm models/sensevoice.tar.bz2
fi

if [ -f "models/silero_vad.onnx" ]; then
    info "Silero VAD 模型已存在，跳过"
else
    info "下载 Silero VAD 模型 (~2.3MB)..."
    wget -q --show-progress -O models/silero_vad.onnx "$VAD_URL"
fi

# --- onnxruntime 符号链接 ---
info "配置 onnxruntime 符号链接..."
ORT_SO=$(find .venv -name "libonnxruntime.so.*" -path "*/onnxruntime/capi/*" | head -1)
if [ -n "$ORT_SO" ]; then
    ln -sf "$(realpath "$ORT_SO")" .venv/lib/python3.12/site-packages/sherpa_onnx.libs/libonnxruntime.so
else
    warn "未找到 libonnxruntime.so，sherpa-onnx 可能无法运行"
fi

# --- systemd 服务 ---
info "配置 systemd 用户服务..."
mkdir -p ~/.config/systemd/user
cp voice-input.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable voice-input
systemctl --user enable ydotool 2>/dev/null || true

echo ""
echo "========================================="
info "安装完成！"
echo "========================================="
echo ""
if [ "$NEED_RELOGIN" = "1" ]; then
    warn "请重新登录以使 input 组权限生效"
    warn "登录后服务会自动启动"
else
    info "启动服务..."
    systemctl --user restart ydotool 2>/dev/null || true
    systemctl --user restart voice-input
    echo ""
    info "按 Caps Lock 开始语音输入！"
fi
