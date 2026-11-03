import tkinter as tk
from tkinter import ttk

import config

def build_ui(gui):
                main = ttk.Frame(
                    gui.root,
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

                gui.ip_var = tk.StringVar(
                    value=config.DEFAULT_DEST_IP
                )

                ttk.Entry(
                    config_frame,
                    textvariable=gui.ip_var,
                    width=20
                ).grid(row=0, column=1, sticky="w", padx=10)


                gui.connect_button = ttk.Button(
                    config_frame,
                    text="Connect",
                    command=gui.connect
                )

                gui.connect_button.grid(
                    row=0,
                    column=2,
                    sticky="w",
                    padx=(0, 10)
                )

                ttk.Label(
                    config_frame,
                    text="Microphone:"
                ).grid(
                    row=1,
                    column=0,
                    sticky="w",
                    pady=5
                )

                gui.device_var = tk.StringVar()

                gui.device_combo = ttk.Combobox(
                    config_frame,
                    textvariable=gui.device_var,
                    width=48,
                    state="readonly"
                )

                gui.device_combo.grid(
                    row=1,
                    column=1,
                    columnspan=2,
                    sticky="w",
                    padx=10
                )

                ttk.Button(
                    config_frame,
                    text="⟳",
                    command=gui.refresh_devices,
                    width=2
                ).grid(
                    row=1,
                    column=3,
                    sticky="w",
                    padx=(0, 10)
                )
                ttk.Label(
                    config_frame,
                    text="Opus bitrate:"
                ).grid(row=2, column=0, sticky="w", pady=5)

                gui.bitrate_var = tk.StringVar(
                    value="48000"
                )

                gui.bitrate_combo = ttk.Combobox(
                    config_frame,
                    textvariable=gui.bitrate_var,
                    values=[
                        "16000",
                        "24000",
                        "32000",
                        "48000",
                        "64000",
                        "96000"
                    ],
                    width=20,
                    state="readonly"
                )

                gui.bitrate_combo.grid(
                    row=2,
                    column=1,
                    sticky="w",
                    padx=10
                )

                # ttk.Label(
                #     config_frame,
                #     text="Sample rate:"
                # ).grid(row=2, column=2, sticky="w")

                # ttk.Label(
                #     config_frame,
                #     text="48000 Hz / Mono / 20 ms"
                # ).grid(
                #     row=2,
                #     column=3,
                #     sticky="w",
                #     padx=10
                # )

                ttk.Label(
                    config_frame,
                    text="Volume:"
                ).grid(
                    row=3,
                    column=0,
                    sticky="w",
                    pady=5
                )

                gui.volume_var = tk.DoubleVar(
                    value=100.0
                )

                volume_frame = ttk.Frame(config_frame)

                volume_frame.grid(
                    row=3,
                    column=1,
                    columnspan=3,
                    sticky="w",
                    padx=10
                )

                gui.volume_slider = ttk.Scale(
                    volume_frame,
                    from_=0,
                    to=100,
                    orient="horizontal",
                    length=200,
                    command=gui.change_volume
                )

                gui.volume_slider.grid(
                    row=0,
                    column=0,
                    sticky="w"
                )

                gui.volume_value = ttk.Label(
                    volume_frame,
                    text="100%"
                )

                gui.volume_value.grid(
                    row=0,
                    column=1,
                    sticky="w",
                    padx=(5, 0)
                )

                # Set initial position AFTER volume_value exists.
                gui.volume_slider.set(100.0)


                control_frame = ttk.Frame(
                    main
                )

                control_frame.pack(
                    fill="x",
                    pady=15
                )

                gui.start_button = ttk.Button(
                    control_frame,
                    text="START",
                    command=gui.start_sender
                )

                gui.start_button.pack(
                    side="left",
                    padx=(0, 10)
                )

                gui.stop_button = ttk.Button(
                    control_frame,
                    text="STOP",
                    command=gui.stop_sender,
                    state="disabled"
                )

                gui.stop_button.pack(
                    side="left",
                    padx=(0, 10)
                )

                gui.recording = False

                gui.record_button = ttk.Button(
                    control_frame,
                    text="RECORD",
                    command=gui.toggle_record
                )

                gui.record_button.pack(
                    side="left",
                    padx=(0, 10)
                )

                gui.loop_button = ttk.Button(
                    control_frame,
                    text="LOOP",
                    command=gui.start_loop,
                    state="disabled"
                )

                gui.loop_button.pack(
                    side="left"
                )

                gui.status_label = ttk.Label(
                    control_frame,
                    text="Status: STOPPED",
                    font=("Arial", 11, "bold")
                )

                gui.status_label.pack(
                    side="right"
                )

                gui.record_dot = tk.Label(
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

                gui.stats_vars = {}

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

                    gui.stats_vars[key] = var

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

                gui.log_text = tk.Text(
                    log_frame,
                    height=8,
                    width=75,
                    state="disabled"
                )
                gui.log_text.pack(
                    side="left",
                    fill="both",
                    expand=True
                )

                scrollbar = ttk.Scrollbar(
                    log_frame,
                    orient="vertical",
                    command=gui.log_text.yview
                )
                scrollbar.pack(
                    side="right",
                    fill="y"
                )

                gui.log_text.configure(
                    yscrollcommand=scrollbar.set
                )