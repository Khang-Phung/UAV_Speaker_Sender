import math

import numpy as np


class InputFilter:
    """
    Xử lý từng frame int16 (mặc định 960 mẫu @ 48 kHz = 20 ms).
    - High-pass: loại ù nền, gió, rung bàn, DC offset
    - Noise gate: giảm noise khi im lặng (có attack/release, không bị click)
    Phải dùng 1 instance cho 1 luồng âm thanh liên tục (giữ state giữa các frame).
    """

    def __init__(
        self,
        rate,
        hp_hz=80,
        gate_db=-50,
        attack_ms=5,
        release_ms=150,
        frame_ms=20
    ):
        # Biquad high-pass Butterworth bậc 2 (tự tính, không cần scipy)
        w0 = 2 * math.pi * hp_hz / rate
        alpha = math.sin(w0) / (2 * (1 / math.sqrt(2)))
        cosw = math.cos(w0)

        a0 = 1 + alpha
        self.b0 = ((1 + cosw) / 2) / a0
        self.b1 = (-(1 + cosw)) / a0
        self.b2 = ((1 + cosw) / 2) / a0
        self.a1 = (-2 * cosw) / a0
        self.a2 = (1 - alpha) / a0

        self.z1 = 0.0
        self.z2 = 0.0

        # Ngưỡng gate theo biên độ int16
        self.thresh = 32768 * 10 ** (gate_db / 20)

        self.gain = 0.0
        self.a_att = 1 - np.exp(-frame_ms / attack_ms)
        self.a_rel = 1 - np.exp(-frame_ms / release_ms)

    def process(self, frame):
        # High-pass biquad (Direct Form II transposed, giữ state giữa các frame)
        b0, b1, b2 = self.b0, self.b1, self.b2
        a1, a2 = self.a1, self.a2
        z1, z2 = self.z1, self.z2

        out = []
        append = out.append
        for v in frame.tolist():
            y = b0 * v + z1
            z1 = b1 * v - a1 * y + z2
            z2 = b2 * v - a2 * y
            append(y)

        self.z1, self.z2 = z1, z2
        x = np.asarray(out, dtype=np.float32)

        # Noise gate
        rms = np.sqrt(np.mean(x * x)) + 1e-9
        target = 1.0 if rms > self.thresh else 0.0
        a = self.a_att if target > self.gain else self.a_rel
        new_gain = self.gain + (target - self.gain) * a

        # Ramp gain trong frame để không bị click ở biên frame
        x *= np.linspace(self.gain, new_gain, len(x), dtype=np.float32)
        self.gain = new_gain

        return np.clip(x, -32768, 32767).astype(np.int16)


def filter_recording(pcm, rate, frame_size):
    """Lọc cả bản ghi 1 lần (frame-by-frame, bỏ phần lẻ cuối nếu không đủ frame)."""
    f = InputFilter(rate)
    out = pcm.copy()
    for i in range(0, len(out) // frame_size * frame_size, frame_size):
        out[i:i + frame_size] = f.process(out[i:i + frame_size])
    return out


def prepare_loop_pcm(buf, frame_size, rate, crossfade_ms=10):
    """
    Trả về buffer có độ dài là bội số của frame_size và nối vòng mượt:
    phần đầu được trộn với phần đuôi tiếp theo (overlap-add), nên khi
    quay lại index 0 không còn bước nhảy biên độ (tiếng 'tách').
    """
    fs = frame_size
    frame_count = len(buf) // fs

    if frame_count == 0:
        return np.empty(0, dtype=np.int16)

    buf = buf[:frame_count * fs]

    fade = int(rate * crossfade_ms / 1000)

    # Bản ghi quá ngắn -> bỏ crossfade
    if frame_count < 4 or fade <= 0:
        return buf.copy()

    out_frames = (len(buf) - fade) // fs
    if out_frames < 1:
        return buf.copy()

    out_len = out_frames * fs
    out = buf[:out_len].astype(np.float32)

    # Đoạn tiếp nối tự nhiên của điểm cuối `out`
    tail = buf[out_len:out_len + fade].astype(np.float32)
    fade = len(tail)

    if fade > 0:
        w = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        out[:fade] = out[:fade] * w + tail * (1.0 - w)

    return np.clip(out, -32768, 32767).astype(np.int16)