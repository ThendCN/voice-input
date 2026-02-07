# voice-input

Linux Wayland 下的离线语音输入法。按 Caps Lock 说话，自动识别后输入到光标位置。

## 特性

- **离线识别** - 基于 SenseVoice + sherpa-onnx，无需联网
- **自动检测语音** - Silero VAD 自动检测说话结束，无需手动停止
- **智能粘贴** - 自动检测终端/GUI 应用，选择正确的粘贴方式
- **Caps Lock 触发** - 通过 keyd 重映射，一键触发

## 依赖

- **系统包**: `keyd` `ydotool` `wl-clipboard` `notify-send`
- **Python**: `sherpa-onnx` `sounddevice` `numpy` `evdev`
- **模型**: SenseVoice int8 (~229MB) + Silero VAD (~2.3MB)
- **桌面环境**: KDE Plasma (Wayland)

## 安装

```bash
# 1. 系统依赖 (Arch Linux)
sudo pacman -S keyd ydotool wl-clipboard

# 2. 用户加入 input 组
sudo usermod -aG input $USER
# 需要重新登录生效

# 3. 配置 keyd (Caps Lock → F13)
sudo tee /etc/keyd/default.conf << 'EOF'
[ids]
*

[main]
capslock = f13
EOF
sudo systemctl enable --now keyd

# 4. 启动 ydotool 守护进程
systemctl --user enable --now ydotool

# 5. Python 依赖
uv sync

# 6. 下载模型
cd models
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
tar xf sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
rm sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
wget -O silero_vad.onnx https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
cd ..

# 7. 创建 onnxruntime 符号链接
ln -sf .venv/lib/python3.12/site-packages/onnxruntime/capi/libonnxruntime.so.* \
       .venv/lib/python3.12/site-packages/sherpa_onnx.libs/libonnxruntime.so

# 8. 开机自启
cp voice-input.service ~/.config/systemd/user/
systemctl --user enable voice-input
```

## 使用

```bash
# 手动启动
./voice-input.sh

# 或通过 systemd
systemctl --user start voice-input
```

按 **Caps Lock** → 说话 → 自动识别并输入到光标位置。

## 工作原理

1. `keyd` 将 Caps Lock 映射为 F13
2. 守护进程通过 `evdev` 监听 F13 按键事件
3. `sounddevice` 录音 + `Silero VAD` 自动检测说话结束
4. `SenseVoice` 离线语音识别
5. `wl-copy` 写入剪贴板 + `ydotool` 模拟粘贴（智能检测终端/GUI）
