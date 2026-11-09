import socket
import opuslib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os
import struct
import time
import sounddevice as sd
import numpy as np
import queue
import threading
import config
from sender.input_filter import InputFilter, filter_recording, prepare_loop_pcm
from sender_state import SenderState
from sender.tcp_control import TcpControl

# ==========================================================
# AUDIO SENDER
# ==========================================================

class AudioSender:
    # Thời gian crossfade ở điểm nối của LOOP (ms)
    LOOP_CROSSFADE_MS = 10

    def __init__(self, gui):
        self.gui = gui

        # --------------------------------------------------
        # Network / Audio
        # --------------------------------------------------
        self.sock = None
        self.stream = None
        self.encoder = None
        self.aesgcm = AESGCM(config.KEY)

        # --------------------------------------------------
        # Live microphone queue
        # --------------------------------------------------
        self.pcm_queue = queue.Queue(maxsize=10)
        self.pcm_buffer = np.empty(0, dtype=np.int16)

        # --------------------------------------------------
        # Recorded PCM
        # record_chunks: gom trong callback (append O(1))
        # record_buffer: ghép 1 lần khi stop_recording
        # --------------------------------------------------
        self.record_chunks = []
        self.record_buffer = np.empty(0, dtype=np.int16)

        # --------------------------------------------------
        # Statistics
        # --------------------------------------------------
        self.seq = 0
        self.total_frames = 0
        self.total_bytes = 0

        self.last_send_time = None
        self.total_interval_ms = 0.0
        self.interval_count = 0
        self.max_interval_ms = 0.0

        # --------------------------------------------------
        # State / threading
        # --------------------------------------------------
        self.state = SenderState.DISCONNECTED
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.RLock()

        # --------------------------------------------------
        # Volume
        # --------------------------------------------------
        self.volume = 1.0

        # --------------------------------------------------
        # Input filter (GUI có thể gán filter_enabled = True/False)
        # --------------------------------------------------
        self.filter_enabled = True
        self.input_filter = None

        # --------------------------------------------------
        # TCP
        # --------------------------------------------------
        self.tcp = TcpControl(self._on_tcp_message, self._on_tcp_disconnect)

    # ======================================================
    # GUI HELPERS (tránh gọi Tkinter trực tiếp từ thread khác)
    # ======================================================

    def _gui_call(self, fn, *args, **kwargs):
        """Nếu gui có .root (Tkinter) thì đẩy sang main thread bằng after()."""
        root = getattr(self.gui, "root", None)
        if root is not None:
            try:
                root.after(0, lambda: fn(*args, **kwargs))
                return
            except Exception:
                pass
        fn(*args, **kwargs)

    def _log(self, msg):
        self._gui_call(self.gui.log, msg)

    def _set_gui_state(self, state):
        self._gui_call(self.gui.set_state, state)

    # ======================================================
    # MICROPHONE CALLBACK
    # ======================================================

    def audio_callback(self, indata, frames, time_info, status):
        if status:
            self._log(f"Microphone status: {status}")

        pcm_int16 = (
            np.clip(indata[:, 0], -1.0, 1.0) * 32767
        ).astype(np.int16)

        # RECORD mode: chỉ append, không concatenate (tránh O(n) trong callback)
        if self.state == SenderState.RECORDING:
            self.record_chunks.append(pcm_int16)
            return

        # Các state khác ngoài RUNNING: bỏ qua
        if self.state != SenderState.RUNNING:
            return

        # LIVE mode
        data = pcm_int16.tobytes()
        try:
            self.pcm_queue.put_nowait(data)
        except queue.Full:
            try:
                self.pcm_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.pcm_queue.put_nowait(data)
            except queue.Full:
                pass

    # ======================================================
    # INITIALIZE NETWORK
    # ======================================================

    def _reset_stats(self):
        self.seq = 0
        self.last_send_time = None
        self.total_frames = 0
        self.total_bytes = 0
        self.total_interval_ms = 0.0
        self.interval_count = 0
        self.max_interval_ms = 0.0

    def init_network(self, bitrate):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)

        self.encoder = opuslib.Encoder(
            config.RATE,
            config.CHANNELS,
            opuslib.APPLICATION_AUDIO
        )
        self.encoder.bitrate = int(bitrate)

        self._reset_stats()

    # ======================================================
    # SENDER THREAD MANAGEMENT
    # ======================================================

    def _join_sender_thread(self):
        """Báo thread cũ dừng và đợi nó thoát hẳn trước khi làm gì tiếp."""
        self.stop_event.set()

        t = self.thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)

        self.thread = None

    def _start_sender_thread(self, dest_ip, dest_port, mode, loop_pcm=None):
        self._join_sender_thread()

        # Mỗi phiên có 1 Event riêng -> thread cũ không thể bị "sống lại"
        self.stop_event = threading.Event()

        self.thread = threading.Thread(
            target=self.sender_loop,
            args=(dest_ip, dest_port, mode, self.stop_event, loop_pcm),
            daemon=True
        )
        self.thread.start()

    # ======================================================
    # START LIVE
    # ======================================================

    def start_live(self, dest_ip, device, bitrate):
        with self.lock:
            if self.state != SenderState.STOPPED:
                return

            try:
                self.init_network(bitrate)

                # Filter mới cho mỗi phiên (reset state)
                self.input_filter = InputFilter(config.RATE)

                self.pcm_buffer = np.empty(0, dtype=np.int16)

                while True:
                    try:
                        self.pcm_queue.get_nowait()
                    except queue.Empty:
                        break

                self.stream = sd.InputStream(
                    device=device,
                    samplerate=config.RATE,
                    channels=config.CHANNELS,
                    dtype="float32",
                    blocksize=0,
                    latency="low",
                    callback=self.audio_callback
                )

                # State phải là RUNNING trước khi stream chạy
                self.state = SenderState.RUNNING
                self.stream.start()

                self._start_sender_thread(
                    dest_ip,
                    int(config.DEFAULT_DEST_PORT),
                    "live"
                )

                self._log(
                    f"Started: {dest_ip}:{config.DEFAULT_DEST_PORT} | "
                    f"Device={device} | Bitrate={bitrate} bps"
                )

            except Exception:
                self.state = SenderState.STOPPED
                self._join_sender_thread()

                if self.stream:
                    try:
                        self.stream.stop()
                        self.stream.close()
                    except Exception:
                        pass

                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass

                self.stream = None
                self.sock = None
                self.encoder = None
                raise

    # ======================================================
    # START / STOP RECORDING
    # ======================================================

    def start_recording(self, device):
        with self.lock:
            if self.state != SenderState.STOPPED:
                return

            self.record_chunks = []
            self.record_buffer = np.empty(0, dtype=np.int16)

            try:
                self.stream = sd.InputStream(
                    device=device,
                    samplerate=config.RATE,
                    channels=config.CHANNELS,
                    dtype="float32",
                    blocksize=0,
                    latency="low",
                    callback=self.audio_callback
                )

                self.state = SenderState.RECORDING
                self.stream.start()

                self._log("Recording started.")

            except Exception:
                self.state = SenderState.STOPPED

                if self.stream:
                    try:
                        self.stream.stop()
                        self.stream.close()
                    except Exception:
                        pass

                self.stream = None
                raise

    def stop_recording(self):
        with self.lock:
            if self.state != SenderState.RECORDING:
                return

            # Dừng stream TRƯỚC để không còn callback nào ghi thêm
            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None

            self.state = SenderState.STOPPED

            # Ghép tất cả chunk 1 lần duy nhất
            if self.record_chunks:
                self.record_buffer = np.concatenate(self.record_chunks)
            else:
                self.record_buffer = np.empty(0, dtype=np.int16)
            self.record_chunks = []

            # Lọc bản ghi 1 lần (LOOP sẽ phát lại bản đã lọc)
            if self.filter_enabled and len(self.record_buffer) > 0:
                self.record_buffer = filter_recording(
                    self.record_buffer, config.RATE, config.FRAME_SIZE
                )

            samples = len(self.record_buffer)
            duration = samples / config.RATE

            self._log(
                f"Recording stopped | "
                f"Samples={samples} | Duration={duration:.2f} s"
            )

    # ======================================================
    # START / STOP LOOP
    # ======================================================

    def start_loop(self):
        with self.lock:
            if len(self.record_buffer) == 0:
                self._log("Cannot LOOP: recording buffer is empty.")
                return

            if self.state != SenderState.STOPPED:
                return

            try:
                dest_ip = self.gui.ip_var.get().strip()
                bitrate = int(self.gui.bitrate_var.get().strip())

                loop_pcm = prepare_loop_pcm(
                    self.record_buffer,
                    config.FRAME_SIZE,
                    config.RATE,
                    self.LOOP_CROSSFADE_MS
                )
                if len(loop_pcm) == 0:
                    self._log("Cannot LOOP: recording shorter than 1 frame.")
                    return

                self.init_network(bitrate)

                self.state = SenderState.LOOPING

                self._start_sender_thread(
                    dest_ip,
                    int(config.DEFAULT_DEST_PORT),
                    "loop",
                    loop_pcm
                )

                self._log(
                    f"Loop started | "
                    f"Samples={len(loop_pcm)} | "
                    f"Dest={dest_ip}:{config.DEFAULT_DEST_PORT} | "
                    f"Bitrate={bitrate}"
                )

            except Exception:
                self.state = SenderState.STOPPED
                self._join_sender_thread()

                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass

                self.sock = None
                self.encoder = None
                raise

    def stop_loop(self):
        with self.lock:
            if self.state != SenderState.LOOPING:
                return
            self.stop()

    # ======================================================
    # MAIN SENDER LOOP
    # ======================================================

    def sender_loop(self, dest_ip, dest_port, mode, stop_event, loop_pcm=None):
        try:
            if mode == "loop":
                self._run_loop(loop_pcm, dest_ip, dest_port, stop_event)
            else:
                self._run_live(dest_ip, dest_port, stop_event)

        except Exception as e:
            # Dừng chủ động thì không báo lỗi
            if not stop_event.is_set():
                self._log(f"Sender error: {e}")
                self._gui_call(self.gui.request_stop_from_error)

    def _run_loop(self, pcm, dest_ip, dest_port, stop_event):
        frame_size = config.FRAME_SIZE
        frame_count = len(pcm) // frame_size

        if frame_count == 0:
            return

        # 960 samples / 48000 Hz = 20 ms
        frame_interval = frame_size / config.RATE

        next_send_time = time.monotonic()
        index = 0

        while not stop_event.is_set():
            if index >= frame_count:
                index = 0

            start = index * frame_size
            pcm_frame = pcm[start:start + frame_size]
            index += 1

            wait_time = next_send_time - time.monotonic()

            if wait_time > 0:
                # wait() thoát ngay khi stop_event được set
                if stop_event.wait(wait_time):
                    break
            elif -wait_time > 0.1:
                # Bị trễ > 100 ms: resync, không gửi dồn một loạt gói
                next_send_time = time.monotonic()

            self.send_pcm_frame(pcm_frame, dest_ip, dest_port)

            next_send_time += frame_interval

    def _run_live(self, dest_ip, dest_port, stop_event):
        frame_size = config.FRAME_SIZE

        while not stop_event.is_set():
            try:
                pcm_bytes = self.pcm_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            pcm_chunk = np.frombuffer(pcm_bytes, dtype=np.int16)

            if len(self.pcm_buffer) == 0:
                self.pcm_buffer = pcm_chunk.copy()
            else:
                self.pcm_buffer = np.concatenate((self.pcm_buffer, pcm_chunk))

            while (
                not stop_event.is_set()
                and len(self.pcm_buffer) >= frame_size
            ):
                pcm_frame = self.pcm_buffer[:frame_size]
                self.pcm_buffer = self.pcm_buffer[frame_size:]

                # Lọc noise (high-pass + gate)
                if self.filter_enabled and self.input_filter:
                    pcm_frame = self.input_filter.process(pcm_frame)

                self.send_pcm_frame(pcm_frame, dest_ip, dest_port)

    # ======================================================
    # ENCODE + AES-GCM + UDP
    # ======================================================

    def send_pcm_frame(self, pcm_frame, dest_ip, dest_port):
        encoder = self.encoder
        sock = self.sock

        if encoder is None or sock is None:
            return

        # --------------------------------------------------
        # Volume (có clip để không bị tràn int16)
        # --------------------------------------------------
        if self.volume != 1.0:
            pcm_frame = np.clip(
                pcm_frame.astype(np.float32) * self.volume,
                -32768,
                32767
            ).astype(np.int16)

        # --------------------------------------------------
        # Opus encode
        # --------------------------------------------------
        encode_start = time.perf_counter()

        opus_packet = encoder.encode(
            pcm_frame.tobytes(),
            config.FRAME_SIZE
        )

        encode_time = (time.perf_counter() - encode_start) * 1000

        # --------------------------------------------------
        # Payload: 4 bytes seq + 8 bytes reserved + Opus
        # --------------------------------------------------
        reserved = 0

        payload = struct.pack("<Id", self.seq, reserved) + opus_packet

        # --------------------------------------------------
        # AES-GCM
        # --------------------------------------------------
        nonce = os.urandom(12)
        encrypted = self.aesgcm.encrypt(nonce, payload, None)
        packet = nonce + encrypted

        # --------------------------------------------------
        # UDP send
        # --------------------------------------------------
        send_start = time.perf_counter()

        sock.sendto(packet, (dest_ip, dest_port))

        send_time = (time.perf_counter() - send_start) * 1000

        # --------------------------------------------------
        # Send interval
        # --------------------------------------------------
        now = time.perf_counter()

        if self.last_send_time is not None:
            interval_ms = (now - self.last_send_time) * 1000
            self.total_interval_ms += interval_ms
            self.interval_count += 1
            if interval_ms > self.max_interval_ms:
                self.max_interval_ms = interval_ms

        self.last_send_time = now

        if self.interval_count > 0:
            avg_interval_ms = self.total_interval_ms / self.interval_count
        else:
            avg_interval_ms = 0

        # --------------------------------------------------
        # Statistics
        # --------------------------------------------------
        packet_size = len(packet)

        self.total_frames += 1
        self.total_bytes += packet_size

        self._gui_call(
            self.gui.update_stats,
            seq=self.seq,
            opus_size=len(opus_packet),
            packet_size=packet_size,
            interval_ms=avg_interval_ms,
            encode_ms=encode_time,
            send_ms=send_time,
            queue_size=self.pcm_queue.qsize(),
            pcm_size=len(self.pcm_buffer),
            total_frames=self.total_frames,
            total_bytes=self.total_bytes
        )

        self.seq += 1

    # ======================================================
    # STOP EVERYTHING
    # ======================================================

    def stop(self):
        with self.lock:
            # Đang record thì kết thúc record đàng hoàng (giữ bản ghi)
            if self.state == SenderState.RECORDING:
                self.stop_recording()
                return

            # 1) Dừng sender thread và đợi nó thoát
            self._join_sender_thread()

            # 2) Dừng microphone
            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
            self.stream = None

            # 3) Đóng UDP (sau khi thread đã thoát)
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass

            self.sock = None
            self.encoder = None
            self.input_filter = None

            self.state = SenderState.STOPPED

            # record_buffer KHÔNG bị xóa

            self._log(
                f"Stopped | "
                f"Frames={self.total_frames} | "
                f"Data={self.total_bytes} bytes | "
                f"MaxInterval={self.max_interval_ms:.1f} ms"
            )

            self.last_send_time = None
            self.total_interval_ms = 0.0
            self.interval_count = 0
            self.max_interval_ms = 0.0

    def stop_activity(self):
        """Dừng bất cứ thứ gì đang chạy (record / live / loop)."""
        with self.lock:
            if self.state == SenderState.RECORDING:
                self.stop_recording()
            elif self.state in (SenderState.RUNNING, SenderState.LOOPING):
                self.stop()

       # ======================================================
    # TCP
    # ======================================================

    @property
    def tcp_connected(self):
        return self.tcp.connected

    def send_tcp_message(self, ip, port, message):
        return self.tcp.connect_and_send(ip, port, message)

    def _on_tcp_message(self, message):
        """Chạy trong TCP thread: server gửi gì cũng dừng và về STOPPED."""
        with self.lock:
            self.stop_activity()
            self.state = SenderState.STOPPED
        self._set_gui_state(SenderState.STOPPED)

    def _on_tcp_disconnect(self):
        """Chạy trong TCP thread: server đóng hoặc lỗi socket."""
        with self.lock:
            self.stop_activity()
            self.state = SenderState.DISCONNECTED
        self._set_gui_state(SenderState.DISCONNECTED)

    def disconnect(self):
        self.tcp.close()
        with self.lock:
            self.stop_activity()
            self.state = SenderState.DISCONNECTED
        self._set_gui_state(SenderState.DISCONNECTED)
        print("Disconnected")