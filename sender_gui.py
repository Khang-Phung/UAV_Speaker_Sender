import tkinter as tk
from tkinter import ttk, messagebox
import time
import config
import sounddevice as sd

from sender_state import SenderState

from audio_sender import AudioSender

from gui.layout import build_ui


class SenderGUI:
    def __init__(self, root):
        self.root = root

        self.root.title("UAV Realtime Audio Sender")
        self.root.geometry("650x600")
        self.root.resizable(False, False)
        self.state = SenderState.DISCONNECTED
        self.sender = AudioSender(self)
        build_ui(self)
        self.refresh_devices()
        
        self.set_state(
        SenderState.DISCONNECTED
    )   

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.on_close
        )

    def change_volume(self, value):
        volume_percent = float(value)

        self.volume_var.set(
            volume_percent
        )

        self.sender.volume = (
            volume_percent / 100.0
        )

        self.volume_value.config(
            text=f"{volume_percent:.0f}%"
        )

    def connect(self):
        ip = self.ip_var.get().strip()

        if self.state != SenderState.DISCONNECTED:
            self.sender.disconnect()  
            return 

        if not ip:
            messagebox.showerror(
                "Input Error",
                "Destination IP is empty."
            )
            return

        success = self.sender.send_tcp_message(
            ip,
            config.DEFAULT_TCP_PORT,
            "START"
        )

        if not success:
            messagebox.showerror(
                "TCP Error",
                "Connection Failed."
            )

            return

        # Tiếp tục xử lý start UDP/audio ở đây

    def refresh_devices(self):
        try:
            devices = sd.query_devices()

            input_devices = []

            for i, device in enumerate(devices):
                if device["max_input_channels"] > 0:
                    name = device["name"]
                    input_devices.append(
                        f"{i}: {name}"
                    )

            self.device_combo["values"] = input_devices

            if input_devices:
                # Prefer system default input device.
                default_input = sd.default.device[0]

                selected = None

                for item in input_devices:
                    if item.startswith(
                        f"{default_input}:"
                    ):
                        selected = item
                        break

                if selected is None:
                    selected = input_devices[0]

                self.device_var.set(selected)

            self.log(
                f"Found {len(input_devices)} input device(s)."
            )

        except Exception as e:
            messagebox.showerror(
                "Audio Device Error",
                str(e)
            )

    def get_selected_device(self):
        value = self.device_var.get()

        if not value:
            return "default"

        # Extract device index from "3: Device Name".
        try:
            return int(
                value.split(":", 1)[0]
            )
        except Exception:
            return "default"


    def toggle_record(self):

        if self.state == SenderState.STOPPED:

            device = self.get_selected_device()

            self.sender.start_recording(
                device
            )

            self.set_state(
                SenderState.RECORDING
            )

        elif self.state == SenderState.RECORDING:

            self.sender.stop_recording()

            self.set_state(
                SenderState.STOPPED
            )


    def start_loop(self):

        if self.state != SenderState.STOPPED:
            return

        if len(self.sender.record_buffer) == 0:
            self.log(
                "Cannot LOOP: recording buffer is empty."
            )
            return

        self.sender.start_loop()

        self.set_state(
            SenderState.LOOPING
        )


    def start_sender(self):

        if self.state != SenderState.STOPPED:
            return

        ip = self.ip_var.get().strip()
        bitrate_text = self.bitrate_var.get().strip()

        if not ip:
            messagebox.showerror(
                "Input Error",
                "Destination IP is empty."
            )
            return

        try:
            bitrate = int(bitrate_text)

        except ValueError:
            messagebox.showerror(
                "Input Error",
                "Invalid Opus bitrate."
            )
            return

        device = self.get_selected_device()

        try:
            self.sender.start_live(
                ip,
                device,
                bitrate
            )

            self.set_state(
                SenderState.RUNNING
            )

        except Exception as e:
            messagebox.showerror(
                "Start Error",
                str(e)
            )


    def stop_sender(self):

        if self.state == SenderState.RUNNING:

            self.sender.stop()

        elif self.state == SenderState.RECORDING:

            self.sender.stop_recording()

        elif self.state == SenderState.LOOPING:

            self.sender.stop_loop()

        self.set_state(
            SenderState.STOPPED
        )

    def update_stats(
        self,
        seq,
        opus_size,
        packet_size,
        interval_ms,
        encode_ms,
        send_ms,
        queue_size,
        pcm_size,
        total_frames,
        total_bytes
    ):
        def update():
            self.stats_vars["seq"].set(
                str(seq)
            )

            self.stats_vars["opus"].set(
                f"{opus_size} bytes"
            )

            self.stats_vars["packet"].set(
                f"{packet_size} bytes"
            )

            self.stats_vars["interval"].set(
                f"{interval_ms:.3f} ms"
            )

            self.stats_vars["encode"].set(
                f"{encode_ms:.3f} ms"
            )

            self.stats_vars["send"].set(
                f"{send_ms:.3f} ms"
            )

            self.stats_vars["queue"].set(
                str(queue_size)
            )

            self.stats_vars["pcm"].set(
                f"{pcm_size} samples"
            )

            self.stats_vars["frames"].set(
                str(total_frames)
            )

            self.stats_vars["bytes"].set(
                f"{total_bytes:,} bytes"
            )

        self.root.after(
            0,
            update
        )

    def set_status(self, status):
        self.status_label.config(
            text=f"Status: {status}"
        )

        if status in ("RUNNING", "RECORDING", "LOOPING"):
            self.record_dot.pack(
                side="right",
                padx=(8, 0)
            )
        else:
            self.record_dot.pack_forget()



    def log(self, message):
        def update():
            self.log_text.config(
                state="normal"
            )

            self.log_text.insert(
                "end",
                f"[{time.strftime('%H:%M:%S')}] {message}\n"
            )

            self.log_text.see("end")

            self.log_text.config(
                state="disabled"
            )

        self.root.after(
            0,
            update
        )

    def request_stop_from_error(self):
        self.root.after(
            0,
            self.sender.stop
        )

    def on_close(self):
        self.sender.stop()
        self.root.destroy()

    def set_state(self, state):

        self.state = state

        if state == SenderState.STOPPED:

            self.start_button.config(
                state="normal"
            )

            self.stop_button.config(
                state="disabled"
            )

            self.record_button.config(
                state="normal",
                text="RECORD"
            )

            if len(self.sender.record_buffer) > 0:
                self.loop_button.config(
                    state="normal"
                )
            else:
                self.loop_button.config(
                    state="disabled"
                )

            self.connect_button.config(
                state="normal",
                text="disconnect"
            )

            self.set_status(
                "STOPPED"
            )

        elif state == SenderState.RUNNING:

            self.start_button.config(
                state="disabled"
            )

            self.stop_button.config(
                state="normal"
            )

            self.record_button.config(
                state="disabled"
            )

            self.loop_button.config(
                state="disabled"
            )

            self.set_status(
                "RUNNING"
            )

        elif state == SenderState.RECORDING:

            self.start_button.config(
                state="disabled"
            )

            self.stop_button.config(
                state="disabled"
            )

            self.record_button.config(
                state="normal",
                text="RECORDING"
            )

            self.loop_button.config(
                state="disabled"
            )

            self.set_status(
                "RECORDING"
            )

        elif state == SenderState.LOOPING:

            self.start_button.config(
                state="disabled"
            )

            self.stop_button.config(
                state="normal"
            )

            self.record_button.config(
                state="disabled"
            )

            self.loop_button.config(
                state="disabled"
            )

            self.set_status(
                "LOOPING"
            )


        elif state == SenderState.DISCONNECTED:

            self.start_button.config(
                state="disabled"
            )

            self.stop_button.config(
                state="disabled"
            )

            self.record_button.config(
                state="disabled"
            )

            self.loop_button.config(
                state="disabled"
            )

            self.connect_button.config(
                state="normal",
                text="connect"
            )

            self.set_status(
                "DISCONNECTED"
            )