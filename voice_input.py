#!/usr/bin/env python3
"""语音输入法 - 常驻守护进程，监听 Caps Lock(F13) 触发录音识别"""

import os
import sys
import subprocess
import signal
import numpy as np
import sounddevice as sd
import sherpa_onnx
import evdev
from evdev import ecodes

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(SCRIPT_DIR, "models")
SENSEVOICE_DIR = os.path.join(
    MODELS_DIR, "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
)
PID_FILE = os.path.join(SCRIPT_DIR, ".voice-input.pid")

SAMPLE_RATE = 16000
SILENCE_TIMEOUT = 0.8
MAX_RECORD_SECONDS = 30
WAIT_FOR_SPEECH_TIMEOUT = 5
TRIGGER_KEY = ecodes.KEY_F13

TERMINALS = {"org.kde.konsole", "ghostty", "com.mitchellh.ghostty",
             "kitty", "alacritty", "foot", "wezterm", "xterm", "urxvt"}

KWIN_SCRIPT = os.path.join(SCRIPT_DIR, "kwin_get_wclass.js")


def notify(msg, urgency="normal"):
    subprocess.Popen(
        ["notify-send", "-u", urgency, "-t", "2000", "语音输入", msg],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def acquire_lock():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            return False
        except (ProcessLookupError, ValueError):
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def create_recognizer():
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=os.path.join(SENSEVOICE_DIR, "model.int8.onnx"),
        tokens=os.path.join(SENSEVOICE_DIR, "tokens.txt"),
        num_threads=4,
        use_itn=True,
        language="",
        debug=False,
    )


def create_vad():
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = os.path.join(MODELS_DIR, "silero_vad.onnx")
    config.silero_vad.min_silence_duration = SILENCE_TIMEOUT
    config.sample_rate = SAMPLE_RATE
    return config


def find_keyd_keyboard():
    """查找 keyd 虚拟键盘设备"""
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if "keyd virtual keyboard" in dev.name:
            return dev
    return None


def record_and_recognize(recognizer, vad_config):
    """录音并使用 VAD 检测说话结束，然后识别"""
    vad = sherpa_onnx.VoiceActivityDetector(
        vad_config, buffer_size_in_seconds=MAX_RECORD_SECONDS
    )
    notify("🎤 正在录音...")

    window_size = vad.config.silero_vad.window_size
    samples_per_read = int(0.1 * SAMPLE_RATE)
    buffer = np.array([], dtype=np.float32)
    total_samples = 0
    max_samples = MAX_RECORD_SECONDS * SAMPLE_RATE
    speech_started = False

    try:
        with sd.InputStream(
            channels=1, dtype="float32", samplerate=SAMPLE_RATE
        ) as stream:
            while total_samples < max_samples:
                samples, _ = stream.read(samples_per_read)
                samples = samples.reshape(-1)
                total_samples += len(samples)
                buffer = np.concatenate([buffer, samples])

                while len(buffer) >= window_size:
                    vad.accept_waveform(buffer[:window_size])
                    buffer = buffer[window_size:]

                if not speech_started and vad.is_speech_detected():
                    speech_started = True

                if (
                    not speech_started
                    and total_samples > WAIT_FOR_SPEECH_TIMEOUT * SAMPLE_RATE
                ):
                    notify("未检测到语音")
                    return None

                if not vad.empty():
                    break

            if vad.empty():
                vad.flush()

    except Exception as e:
        notify(f"录音失败: {e}", "critical")
        return None

    all_samples = []
    while not vad.empty():
        all_samples.append(vad.front.samples)
        vad.pop()

    if not all_samples:
        notify("未检测到语音")
        return None

    audio = np.concatenate(all_samples)
    asr_stream = recognizer.create_stream()
    asr_stream.accept_waveform(SAMPLE_RATE, audio)
    recognizer.decode_stream(asr_stream)
    return asr_stream.result.text.strip() or None


def get_active_window_class():
    """通过 KWin scripting 获取当前活动窗口的 resourceClass"""
    try:
        r = subprocess.run(
            ["qdbus6", "org.kde.KWin", "/Scripting", "loadScript", KWIN_SCRIPT],
            capture_output=True, text=True, timeout=2,
        )
        script_id = r.stdout.strip()
        subprocess.run(
            ["qdbus6", "org.kde.KWin", f"/Scripting/Script{script_id}", "run"],
            capture_output=True, timeout=2,
        )
        r = subprocess.run(
            ["journalctl", "--user", "-n", "5", "--no-pager", "-t", "kwin_wayland"],
            capture_output=True, text=True, timeout=2,
        )
        for line in reversed(r.stdout.splitlines()):
            if "VI_WCLASS:" in line:
                return line.split("VI_WCLASS:", 1)[1].strip()
    except Exception:
        pass
    return ""


def input_text(text):
    """通过剪贴板 + 模拟粘贴将文字输入到光标位置"""
    subprocess.run(["wl-copy", text], check=True)
    wclass = get_active_window_class()
    if wclass in TERMINALS:
        # 终端: Ctrl+Shift+V (29=LCtrl, 42=LShift, 47=V)
        subprocess.run(
            ["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"],
            check=True,
        )
    else:
        # GUI 应用: Ctrl+V
        subprocess.run(
            ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
            check=True,
        )


def main():
    if not acquire_lock():
        print("已有实例在运行", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGTERM, lambda *_: (release_lock(), sys.exit(0)))
    signal.signal(signal.SIGINT, lambda *_: (release_lock(), sys.exit(0)))

    try:
        print("正在加载模型...")
        recognizer = create_recognizer()
        vad_config = create_vad()

        kbd = find_keyd_keyboard()
        if not kbd:
            print("未找到 keyd 虚拟键盘", file=sys.stderr)
            sys.exit(1)

        print(f"已就绪，监听 {kbd.name} ({kbd.path})")
        print("按 Caps Lock 开始语音输入")

        busy = False
        for event in kbd.read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            key_event = evdev.categorize(event)
            if key_event.scancode != TRIGGER_KEY:
                continue
            if key_event.keystate != evdev.KeyEvent.key_down:
                continue
            if busy:
                continue

            busy = True
            try:
                text = record_and_recognize(recognizer, vad_config)
                if text:
                    input_text(text)
                    notify(f"✅ {text}")
            except Exception as e:
                notify(f"错误: {e}", "critical")
            finally:
                busy = False
    finally:
        release_lock()


if __name__ == "__main__":
    main()
