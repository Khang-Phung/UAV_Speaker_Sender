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

        self.sock = None
        self.stream = None
        self.encoder = None
        self.aesgcm = AESGCM(config.KEY)

        self.pcm_queue = queue.Queue(maxsize=5)
        self.pcm_buffer = np.empty(0, dtype=np.int16)

        self.seq = 0
        self.last_send_time = None

        self.total_frames = 0
        self.total_bytes = 0

        self.running = False
        self.thread = None

        # Volume multiplier: 1.0 = 100%
        self.volume = 1.0

    def audio_callback(self, indata, frames, time_info, status):
        if status:
            self.gui.log(f"Microphone status: {status}")

        pcm_int16 = (
            np.clip(
                indata[:, 0] * self.volume,
                -1.0,
                1.0
            ) * 32767
        ).astype(np.int16)
        

        try:
            self.pcm_queue.put_nowait(pcm_int16.tobytes())

        except queue.Full:
            # Drop oldest chunk to keep latency low.
            try:
                self.pcm_queue.get_nowait()
            except queue.Empty:
                pass

            try:
                self.pcm_queue.put_nowait(pcm_int16.tobytes())
            except queue.Full:
                pass

    def start(self, dest_ip, dest_port, device, bitrate):
        if self.running:
            return

        try:
            self.sock = socket.socket(
                socket.AF_INET,
                socket.SOCK_DGRAM
            )

            self.sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_SNDBUF,
                1024 * 1024
            )

            self.encoder = opuslib.Encoder(
                config.RATE,
                config.CHANNELS,
                opuslib.APPLICATION_AUDIO
            )

            self.encoder.bitrate = int(bitrate)

            self.seq = 0
            self.last_send_time = None
            self.total_frames = 0
            self.total_bytes = 0
            self.pcm_buffer = np.empty(0, dtype=np.int16)

            # Clear old PCM chunks before starting.
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

            self.stream.start()

            self.running = True

            self.thread = threading.Thread(
                target=self.sender_loop,
                args=(dest_ip, int(dest_port)),
                daemon=True
            )
            self.thread.start()

            self.gui.set_status("RUNNING")
            self.gui.set_buttons(running=True)
            self.gui.log(
                f"Started: {dest_ip}:{dest_port} | "
                f"Device={device} | Bitrate={bitrate} bps"
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

            raise e

    def sender_loop(self, dest_ip, dest_port):
        try:
            while self.running:

                # Wait for audio from callback.
                pcm_bytes = self.pcm_queue.get(timeout=0.2)

                pcm_chunk = np.frombuffer(
                    pcm_bytes,
                    dtype=np.int16
                )

                if len(self.pcm_buffer) == 0:
                    self.pcm_buffer = pcm_chunk.copy()
                else:
                    self.pcm_buffer = np.concatenate(
                        (
                            self.pcm_buffer,
                            pcm_chunk
                        )
                    )

                # Process every complete 960-sample frame.
                while (
                    self.running
                    and len(self.pcm_buffer) >= config.FRAME_SIZE
                ):
                    pcm_frame = self.pcm_buffer[:config.FRAME_SIZE]

                    self.pcm_buffer = self.pcm_buffer[config.FRAME_SIZE:]

                    # Opus encode.
                    encode_start = time.perf_counter()

                    opus_packet = self.encoder.encode(
                        pcm_frame.tobytes(),
                        config.FRAME_SIZE
                    )

                    encode_time = (
                        time.perf_counter()
                        - encode_start
                    ) * 1000

                    #timestamp = time.time()
                    reserved = 0.0

                    # 4 bytes sequence + 8 bytes timestamp/reserved + Opus.
                    payload = struct.pack(
                        "<Id",
                        self.seq,
                        reserved
                    ) + opus_packet

                    # AES-GCM encryption.
                    nonce = os.urandom(12)

                    encrypted = self.aesgcm.encrypt(
                        nonce,
                        payload,
                        None
                    )

                    # Final packet = nonce + encrypted payload.
                    packet = nonce + encrypted

                    # UDP send.
                    send_start = time.perf_counter()

                    self.sock.sendto(
                        packet,
                        (dest_ip, dest_port)
                    )

                    send_time = (
                        time.perf_counter()
                        - send_start
                    ) * 1000

                    # Send interval.
                    now = time.perf_counter()

                    if self.last_send_time is None:
                        interval_ms = 0
                    else:
                        interval_ms = (
                            now - self.last_send_time
                        ) * 1000

                    self.last_send_time = now

                    packet_size = len(packet)

                    self.total_frames += 1
                    self.total_bytes += packet_size

                    # Update GUI every packet.
                    self.gui.update_stats(
                        seq=self.seq,
                        opus_size=len(opus_packet),
                        packet_size=packet_size,
                        interval_ms=interval_ms,
                        encode_ms=encode_time,
                        send_ms=send_time,
                        queue_size=self.pcm_queue.qsize(),
                        pcm_size=len(self.pcm_buffer),
                        total_frames=self.total_frames,
                        total_bytes=self.total_bytes
                    )

                    self.seq = self.seq + 1

        except queue.Empty:
            pass

        except Exception as e:
            if self.running:
                self.gui.log(f"Sender error: {e}")
                self.gui.request_stop_from_error()

    def stop(self):
        if not self.running:
            return

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

        self.gui.set_status("STOPPED")
        self.gui.set_buttons(running=False)
        self.gui.log(
            f"Stopped | Frames={self.total_frames} | "
            f"Data={self.total_bytes} bytes"
        )

