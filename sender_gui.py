import tkinter as tk
from tkinter import ttk, messagebox
import time
import config
import sounddevice as sd

from audio_sender2 import AudioSender

class SenderGUI:
    def __init__(self, root):
        self.root = root

        self.root.title("UAV Realtime Audio Sender")
        self.root.geometry("650x600")
        self.root.resizable(False, False)

        self.sender = AudioSender(self)
        self.recording = False
        self.looping = False
        self.build_ui()
        self.refresh_devices()

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.on_close
        )


    def build_ui(self):
        main = ttk.Frame(
            self.root,
            padding=15
        )
        main.pack(fill="both", expand=True)

        title = ttk.Label(
            main,
            text="UAV REALTIME AUDIO SENDER",
            font=("Arial", 18, "bold")
        )
        title.pack(pady=(0, 15))

        config_frame = ttk.LabelFrame(
            main,
            text="Connection & Audio",
            padding=10
        )
        config_frame.pack(fill="x")

        ttk.Label(
            config_frame,
            text="Destination IP:"
        ).grid(row=0, column=0, sticky="w", pady=5)

        self.ip_var = tk.StringVar(
            value=config.DEFAULT_DEST_IP
        )

        ttk.Entry(
            config_frame,
            textvariable=self.ip_var,
            width=25
        ).grid(row=0, column=1, sticky="w", padx=10)

        ttk.Label(
            config_frame,
            text="Port:"
        ).grid(row=0, column=2, sticky="w", padx=(20, 0))

        self.port_var = tk.StringVar(
            value=str(config.DEFAULT_DEST_PORT)
        )

        ttk.Entry(
            config_frame,
            textvariable=self.port_var,
            width=10
        ).grid(row=0, column=3, sticky="w", padx=10)

        ttk.Label(
            config_frame,
            text="Microphone:"
        ).grid(row=1, column=0, sticky="w", pady=5)

        self.device_var = tk.StringVar()

        self.device_combo = ttk.Combobox(
            config_frame,
            textvariable=self.device_var,
            width=48,
            state="readonly"
        )

        self.device_combo.grid(
            row=1,
            column=1,
            columnspan=3,
            sticky="w",
            padx=10
        )

        ttk.Label(
            config_frame,
            text="Opus bitrate:"
        ).grid(row=2, column=0, sticky="w", pady=5)

        self.bitrate_var = tk.StringVar(
            value="48000"
        )

        self.bitrate_combo = ttk.Combobox(
            config_frame,
            textvariable=self.bitrate_var,
            values=[
                "16000",
                "24000",
                "32000",
                "48000",
                "64000",
                "96000"
            ],
            width=15,
            state="readonly"
        )

        self.bitrate_combo.grid(
            row=2,
            column=1,
            sticky="w",
            padx=10
        )

        ttk.Label(
            config_frame,
            text="Sample rate:"
        ).grid(row=2, column=2, sticky="w")

        ttk.Label(
            config_frame,
            text="48000 Hz / Mono / 20 ms"
        ).grid(
            row=2,
            column=3,
            sticky="w",
            padx=10
        )

        ttk.Label(
            config_frame,
            text="Volume:"
        ).grid(
            row=3,
            column=0,
            sticky="w",
            pady=5
        )

        self.volume_var = tk.DoubleVar(
            value=100.0
        )

        # Create the label BEFORE creating/setting the slider.
        self.volume_value = ttk.Label(
            config_frame,
            text="100%"
        )

        self.volume_value.grid(
            row=3,
            column=2,
            sticky="w"
        )

        self.volume_slider = ttk.Scale(
            config_frame,
            from_=0,
            to=200,
            orient="horizontal",
            length=200,
            command=self.change_volume
        )

        self.volume_slider.grid(
            row=3,
            column=1,
            sticky="w",
            padx=10
        )

        # Set initial position AFTER volume_value exists.
        self.volume_slider.set(100.0)

        ttk.Button(
            config_frame,
            text="Refresh Devices",
            command=self.refresh_devices
        ).grid(
            row=4,
            column=1,
            sticky="w",
            padx=10,
            pady=(10, 0)
        )
        control_frame = ttk.Frame(
            main
        )

        control_frame.pack(
            fill="x",
            pady=15
        )

        self.start_button = ttk.Button(
            control_frame,
            text="START",
            command=self.start_sender
        )

        self.start_button.pack(
            side="left",
            padx=(0, 10)
        )

        self.stop_button = ttk.Button(
            control_frame,
            text="STOP",
            command=self.stop_sender,
            state="disabled"
        )

        self.stop_button.pack(
            side="left",
            padx=(0, 10)
        )

        self.recording = False

        self.record_button = ttk.Button(
            control_frame,
            text="RECORD",
            command=self.toggle_record
        )

        self.record_button.pack(
            side="left",
            padx=(0, 10)
        )

        self.loop_button = ttk.Button(
            control_frame,
            text="LOOP",
            command=self.start_loop,
            state="disabled"
        )

        self.loop_button.pack(
            side="left"
        )

        self.status_label = ttk.Label(
            control_frame,
            text="Status: STOPPED",
            font=("Arial", 11, "bold")
        )

        self.status_label.pack(
            side="right"
        )

        self.record_dot = tk.Label(
            control_frame,
            text="●",
            font=("Arial", 12),
            fg="red"
        )

        stats_frame = ttk.LabelFrame(
            main,
            text="Realtime Statistics",
            padding=10
        )
        stats_frame.pack(fill="x")

        self.stats_vars = {}

        stats = [
            ("Sequence", "seq"),
            ("Opus", "opus"),
            ("Packet", "packet"),
            ("Interval", "interval"),
            ("Encode", "encode"),
            ("Send", "send"),
            ("Queue", "queue"),
            ("PCM Buffer", "pcm"),
            ("Total Frames", "frames"),
            ("Total Data", "bytes")
        ]

        for row, (label, key) in enumerate(stats):
            ttk.Label(
                stats_frame,
                text=f"{label}:"
            ).grid(
                row=row // 2,
                column=(row % 2) * 2,
                sticky="w",
                padx=5,
                pady=3
            )

            var = tk.StringVar(
                value="-"
            )

            self.stats_vars[key] = var

            ttk.Label(
                stats_frame,
                textvariable=var,
                width=20
            ).grid(
                row=row // 2,
                column=(row % 2) * 2 + 1,
                sticky="w",
                padx=5,
                pady=3
            )

        log_frame = ttk.LabelFrame(
            main,
            text="Log",
            padding=5
        )
        log_frame.pack(
            fill="both",
            expand=True,
            pady=(15, 0)
        )

        self.log_text = tk.Text(
            log_frame,
            height=8,
            width=75,
            state="disabled"
        )
        self.log_text.pack(
            side="left",
            fill="both",
            expand=True
        )

        scrollbar = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview
        )
        scrollbar.pack(
            side="right",
            fill="y"
        )

        self.log_text.configure(
            yscrollcommand=scrollbar.set
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
        if self.recording:
            self.sender.stop_recording()

            self.recording = False

            self.record_button.config(
                text="RECORD"
            )

            self.start_button.config(
                state="normal"
            )

            self.stop_button.config(
                state="disabled"
            )

            self.loop_button.config(
                state="normal"
            )

            self.set_status(
                "STOPPED"
            )

        else:
            device = self.get_selected_device()

            self.sender.start_recording(device)
            
            self.recording = True

            self.record_button.config(
                text="RECORDING"
            )

            self.start_button.config(
                state="disabled"
            )

            self.stop_button.config(
                state="disabled"
            )

            self.loop_button.config(
                state="disabled"
            )

            self.set_status(
                "RECORDING"
            )

    def start_loop(self):
        self.sender.start_loop()
        self.looping = True
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

    def start_sender(self):
        if self.sender.running:
            return
        self.recording = False
        self.looping = False
        ip = self.ip_var.get().strip()
        port_text = self.port_var.get().strip()
        bitrate_text = self.bitrate_var.get().strip()

        if not ip:
            messagebox.showerror(
                "Input Error",
                "Destination IP is empty."
            )
            return

        try:
            port = int(port_text)

            if not 1 <= port <= 65535:
                raise ValueError

        except ValueError:
            messagebox.showerror(
                "Input Error",
                "Port must be between 1 and 65535."
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
                port,
                device,
                bitrate
            )

            self.record_button.config(
                state="disabled"
            )

            self.loop_button.config(
                state="disabled"
            )

        except Exception as e:
            messagebox.showerror(
                "Start Error",
                str(e)
            )

    def stop_sender(self):
        if self.recording:
            self.sender.stop_recording()

            self.recording = False

        elif self.looping:
            self.sender.stop_loop()

            self.looping = False

        else:
            # START live
            self.sender.stop()

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

        self.loop_button.config(
            state="normal"
        )

        self.set_status(
            "STOPPED"
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

    def set_buttons(self, running):
        def update():
            self.start_button.config(
                state="disabled" if running else "normal"
            )

            self.stop_button.config(
                state="normal" if running else "disabled"
            )

        self.root.after(
            0,
            update
        )

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
