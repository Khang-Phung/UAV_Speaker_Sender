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


class AudioSender:
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

        # Temporary PCM buffer for 960-sample frames
        self.pcm_buffer = np.empty(
            0,
            dtype=np.int16
        )

        # --------------------------------------------------
        # Recorded PCM
        # --------------------------------------------------

        self.record_buffer = np.empty(
            0,
            dtype=np.int16
        )

        # --------------------------------------------------
        # Statistics
        # --------------------------------------------------

        self.seq = 0
        self.last_send_time = None

        self.total_frames = 0
        self.total_bytes = 0

        # --------------------------------------------------
        # State
        # --------------------------------------------------

        self.running = False
        self.recording = False
        self.looping = False

        self.thread = None

        # --------------------------------------------------
        # Volume
        # --------------------------------------------------

        self.volume = 1.0

        #testting
        self.last_send_time = None
        self.total_interval_ms = 0.0
        self.interval_count = 0
        
    # ======================================================
    # MICROPHONE CALLBACK
    # ======================================================

    def audio_callback(
        self,
        indata,
        frames,
        time_info,
        status
    ):

        if status:
            self.gui.log(
                f"Microphone status: {status}"
            )

        pcm_int16 = (
            np.clip(
                indata[:, 0],
                -1.0,
                1.0
            ) * 32767
        ).astype(np.int16)

        # --------------------------------------------------
        # RECORD mode
        # --------------------------------------------------

        if self.recording:
            self.record_buffer = np.concatenate(
                (
                    self.record_buffer,
                    pcm_int16
                )
            )

            return

        # --------------------------------------------------
        # LIVE mode
        # --------------------------------------------------

        try:
            self.pcm_queue.put_nowait(
                pcm_int16.tobytes()
            )

        except queue.Full:
            try:
                self.pcm_queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self.pcm_queue.put_nowait(
                    pcm_int16.tobytes()
                )
            except queue.Full:
                pass

    # ======================================================
    # INITIALIZE NETWORK
    # ======================================================

    def init_network(self, bitrate):
        # Close old socket
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

        self.sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        self.sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_SNDBUF,
            1024 * 1024
        )

        # Opus encoder
        self.encoder = opuslib.Encoder(
            config.RATE,
            config.CHANNELS,
            opuslib.APPLICATION_AUDIO
        )

        self.encoder.bitrate = int(bitrate)

        # Reset statistics
        self.seq = 0
        self.last_send_time = None
        self.total_frames = 0
        self.total_bytes = 0

    # ======================================================
    # START LIVE
    # ======================================================

    def start_live(
        self,
        dest_ip,
        dest_port,
        device,
        bitrate
    ):
        if self.running or self.recording or self.looping:
            return

        try:
            # Initialize UDP + Opus
            self.init_network(bitrate)

            # Reset PCM assembly buffer
            self.pcm_buffer = np.empty(
                0,
                dtype=np.int16
            )

            # Clear old microphone queue
            while True:
                try:
                    self.pcm_queue.get_nowait()
                except queue.Empty:
                    break

            # Create microphone stream
            self.stream = sd.InputStream(
                device=device,
                samplerate=config.RATE,
                channels=config.CHANNELS,
                dtype="float32",
                blocksize=0,
                latency="low",
                callback=self.audio_callback
            )

            self.stream.start()

            self.running = True
            self.recording = False
            self.looping = False

            # Sender thread
            self.thread = threading.Thread(
                target=self.sender_loop,
                args=(
                    dest_ip,
                    int(dest_port)
                ),
                daemon=True
            )

            self.thread.start()

            self.gui.set_status("RUNNING")
            self.gui.set_buttons(running=True)

            self.gui.log(
                f"Started: {dest_ip}:{dest_port} | "
                f"Device={device} | "
                f"Bitrate={bitrate} bps"
            )

        except Exception as e:
            self.running = False

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

            raise e

    # ======================================================
    # START RECORDING
    # ======================================================

    def start_recording(self, device):
        if self.running or self.recording or self.looping:
            return

        # New recording replaces old recording
        self.record_buffer = np.empty(
            0,
            dtype=np.int16
        )

        self.recording = True
        self.looping = False

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

            self.stream.start()

            self.gui.log(
                "Recording started."
            )

        except Exception as e:
            self.recording = False

            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass

            self.stream = None

            raise e

    # ======================================================
    # STOP RECORDING
    # ======================================================

    def stop_recording(self):
        if not self.recording:
            return

        self.recording = False

        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

            self.stream = None

        # IMPORTANT:
        # Do NOT clear record_buffer.

        samples = len(
            self.record_buffer
        )

        duration = (
            samples / config.RATE
        )

        self.gui.log(
            f"Recording stopped | "
            f"Samples={samples} | "
            f"Duration={duration:.2f} s"
        )

    # ======================================================
    # START LOOP
    # ======================================================

    def start_loop(self):
        if len(self.record_buffer) == 0:
            self.gui.log(
                "Cannot LOOP: recording buffer is empty."
            )
            return

        if self.looping:
            return

        if self.running or self.recording:
            return

        try:
            # Get settings from GUI
            dest_ip = self.gui.ip_var.get().strip()

            dest_port = int(
                self.gui.port_var.get().strip()
            )

            bitrate = int(
                self.gui.bitrate_var.get().strip()
            )

            # Initialize UDP + Opus
            self.init_network(bitrate)

            self.running = False
            self.recording = False
            self.looping = True

            # Use the same sender_loop()
            self.thread = threading.Thread(
                target=self.sender_loop,
                args=(
                    dest_ip,
                    dest_port
                ),
                daemon=True
            )

            self.thread.start()

            self.gui.log(
                f"Loop started | "
                f"Samples={len(self.record_buffer)} | "
                f"Dest={dest_ip}:{dest_port} | "
                f"Bitrate={bitrate}"
            )

        except Exception as e:
            self.looping = False

            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass

            self.sock = None
            self.encoder = None

            raise e

    # ======================================================
    # STOP LOOP
    # ======================================================

    def stop_loop(self):
        if not self.looping:
            return

        self.looping = False

        self.gui.log(
            "Loop stopped."
        )

    # ======================================================
    # MAIN SENDER LOOP
    # ======================================================

    def sender_loop(
        self,
        dest_ip,
        dest_port
    ):
        try:

            while self.running or self.looping:

                # ==================================================
                # LOOP MODE
                # ==================================================

                if self.looping:

                    if len(self.record_buffer) == 0:
                        self.looping = False
                        continue

                    pcm_source = self.record_buffer

                    buffer_len = len(pcm_source)

                    # Number of complete 960-sample frames
                    frame_count = (
                        buffer_len
                        // config.FRAME_SIZE
                    )

                    if frame_count == 0:
                        self.looping = False
                        continue

                    index = 0

                    # 960 samples / 48000 Hz = 20 ms
                    frame_interval = (
                        config.FRAME_SIZE
                        / config.RATE
                    )

                    next_send_time = time.monotonic()

                    while self.looping:

                        # --------------------------------------------------
                        # Restart from beginning when reaching the end
                        # --------------------------------------------------

                        if (
                            index + config.FRAME_SIZE
                            > buffer_len
                        ):
                            index = 0

                        pcm_frame = pcm_source[
                            index:
                            index + config.FRAME_SIZE
                        ]

                        if len(pcm_frame) < config.FRAME_SIZE:
                            index = 0
                            continue

                        index += config.FRAME_SIZE

                        # --------------------------------------------------
                        # Wait until the scheduled send time
                        # --------------------------------------------------

                        wait_time = (
                            next_send_time
                            - time.monotonic()
                        )

                        if wait_time > 0:
                            time.sleep(wait_time)

                        # --------------------------------------------------
                        # Send 20 ms audio frame
                        # --------------------------------------------------

                        self.send_pcm_frame(
                            pcm_frame,
                            dest_ip,
                            dest_port
                        )

                        # Schedule next frame exactly 20 ms later
                        next_send_time += frame_interval

                    continue

                # ==================================================
                # LIVE MODE
                # ==================================================

                try:
                    pcm_bytes = self.pcm_queue.get(
                        timeout=0.05
                    )
                
                except queue.Empty:
                    continue

                pcm_chunk = np.frombuffer(
                    pcm_bytes,
                    dtype=np.int16
                )

                # Add PCM to assembly buffer
                if len(self.pcm_buffer) == 0:

                    self.pcm_buffer = (
                        pcm_chunk.copy()
                    )

                else:

                    self.pcm_buffer = np.concatenate(
                        (
                            self.pcm_buffer,
                            pcm_chunk
                        )
                    )

                # Extract 960-sample frames
                while (
                    self.running
                    and len(self.pcm_buffer)
                    >= config.FRAME_SIZE
                ):

                    pcm_frame = (
                        self.pcm_buffer[
                            :config.FRAME_SIZE
                        ]
                    )

                    self.pcm_buffer = (
                        self.pcm_buffer[
                            config.FRAME_SIZE:
                        ]
                    )

                    self.send_pcm_frame(
                        pcm_frame,
                        dest_ip,
                        dest_port
                    )

        except Exception as e:

            # Normal LOOP stop should not generate error
            if self.running or self.looping:

                self.gui.log(
                    f"Sender error: {e}"
                )

                self.gui.request_stop_from_error()

    # ======================================================
    # ENCODE + AES-GCM + UDP
    # ======================================================

    def send_pcm_frame(
        self,
        pcm_frame,
        dest_ip,
        dest_port
    ):
        if self.encoder is None:
            return

        if self.sock is None:
            return

        # --------------------------------------------------
        # Opus encode
        # --------------------------------------------------

        encode_start = time.perf_counter()
        pcm_frame = (pcm_frame * self.volume).astype(np.int16)
        opus_packet = self.encoder.encode(
            pcm_frame.tobytes(),
            config.FRAME_SIZE
        )

        encode_time = (
            time.perf_counter()
            - encode_start
        ) * 1000

        # --------------------------------------------------
        # Payload
        #
        # 4 bytes sequence
        # 8 bytes reserved
        # Opus payload
        # --------------------------------------------------

        reserved = 0.0

        payload = (
            struct.pack(
                "<Id",
                self.seq,
                reserved
            )
            + opus_packet
        )

        # --------------------------------------------------
        # AES-GCM
        # --------------------------------------------------

        nonce = os.urandom(12)

        encrypted = self.aesgcm.encrypt(
            nonce,
            payload,
            None
        )

        # nonce + encrypted payload
        packet = nonce + encrypted

        # --------------------------------------------------
        # UDP send
        # --------------------------------------------------

        send_start = time.perf_counter()

        self.sock.sendto(
            packet,
            (
                dest_ip,
                dest_port
            )
        )

        send_time = (
            time.perf_counter()
            - send_start
        ) * 1000

        # --------------------------------------------------
        # Send interval
        # --------------------------------------------------

        now = time.perf_counter()

        if self.last_send_time is None:
            interval_ms = 0
        else:
            interval_ms = (
                now - self.last_send_time
            ) * 1000

            self.total_interval_ms += interval_ms
            self.interval_count += 1

        self.last_send_time = now

        # Average interval
        if self.interval_count > 0:
            avg_interval_ms = (
                self.total_interval_ms
                / self.interval_count
            )
        else:
            avg_interval_ms = 0
        # --------------------------------------------------
        # Statistics
        # --------------------------------------------------

        packet_size = len(packet)

        self.total_frames += 1
        self.total_bytes += packet_size

        self.gui.update_stats(
            seq=self.seq,
            opus_size=len(opus_packet),
            packet_size=packet_size,
            interval_ms=avg_interval_ms, #chuyen thanh avg de quan sat hon
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
        self.running = False
        self.recording = False
        self.looping = False

        self.last_send_time = None
        self.total_interval_ms = 0.0
        self.interval_count = 0

        # --------------------------------------------------
        # Stop microphone
        # --------------------------------------------------

        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

        self.stream = None

        # --------------------------------------------------
        # Close UDP
        # --------------------------------------------------

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

        self.sock = None
        self.encoder = None

        # --------------------------------------------------
        # IMPORTANT:
        # record_buffer is NOT cleared.
        # --------------------------------------------------

        self.gui.set_status(
            "STOPPED"
        )

        self.gui.set_buttons(
            running=False
        )

        self.gui.log(
            f"Stopped | "
            f"Frames={self.total_frames} | "
            f"Data={self.total_bytes} bytes"
        )