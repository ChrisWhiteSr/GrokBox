import tkinter as tk
from tkinter import ttk
from tkinter import scrolledtext
import subprocess
import threading
import queue
import re
import time
import os
from PIL import Image, ImageTk

class GrokBoxGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("GrokBox Status Monitor")
        self.is_fullscreen = False

        self.screen_width  = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        self.window_height = int(self.screen_height * 0.85)
        self.half_width    = self.screen_width // 2
        self.pw_env = {**os.environ, "XDG_RUNTIME_DIR": "/run/user/1000"}

        self.root.geometry(f"{self.half_width}x{self.window_height}+0+0")
        self.root.configure(bg='#000000')

        # Launch xterm on right half
        try:
            subprocess.Popen(
                [
                    "xterm",
                    "-bg", "black",
                    "-fg", "green",
                    "-fa", "Monospace",
                    "-fs", "12",
                    "-geometry", f"80x48+{self.half_width}+0",
                ],
                env=dict(os.environ, DISPLAY=":0")
            )
        except Exception as e:
            print(f"Xterm launch error: {e}")

        self.audio_mgr_win = None
        self.src_window    = None

        # Styling
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame',          background='#000000')
        style.configure('TLabel',          background='#000000', foreground='#00FFCC')
        style.configure('Hotkeys.TLabel',  background='#000000', foreground='#FFFF00')

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        # Header
        header = ttk.Frame(self.root)
        header.grid(row=0, column=0, sticky='ew', pady=(20, 10))
        ttk.Label(header, text="GrokBox", font=('Courier', 42, 'bold')).pack()

        # Model indicator
        self.model_name = self._get_daemon_model()
        style.configure('Model.TLabel', background='#000000', foreground='#888888')
        ttk.Label(header, text=self.model_name, font=('Courier', 12), style='Model.TLabel').pack()

        status_frame = ttk.Frame(header)
        status_frame.pack(pady=5)
        self.status_indicator = ttk.Label(status_frame, text="●", font=('Arial', 18), foreground='#FF0000')
        self.status_indicator.pack(side='left', padx=5)
        self.status_text = ttk.Label(status_frame, text="LISTENING_MODE: ACTIVE", font=('Courier', 14))
        self.status_text.pack(side='left')

        # Main content
        content = ttk.Frame(self.root)
        content.grid(row=1, column=0, sticky='nsew', padx=20, pady=10)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        left_col = ttk.Frame(content)
        left_col.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        left_col.grid_rowconfigure(1, weight=1)

        user_frame = ttk.Frame(left_col)
        user_frame.grid(row=0, column=0, sticky='nsew', pady=(0, 10))
        ttk.Label(user_frame, text="> USER AUDIO TRANSCRIPT", font=('Courier', 12, 'bold')).pack(anchor='w')
        self.user_text = scrolledtext.ScrolledText(user_frame, width=20, height=8, bg='#0a192f', fg='#64ffda',
                                                   font=('Courier', 12), wrap=tk.WORD, borderwidth=1, relief='solid')
        self.user_text.pack(fill='x', pady=5)

        grok_frame = ttk.Frame(left_col)
        grok_frame.grid(row=1, column=0, sticky='nsew')
        ttk.Label(grok_frame, text="> GROK SYNTHESIS", font=('Courier', 12, 'bold')).pack(anchor='w')
        self.grok_text = scrolledtext.ScrolledText(grok_frame, width=20, bg='#112240', fg='#e6f1ff',
                                                   font=('Courier', 14), wrap=tk.WORD, borderwidth=1, relief='solid')
        self.grok_text.pack(fill='both', expand=True, pady=5)

        right_col = ttk.Frame(content)
        right_col.grid(row=0, column=1, sticky='nsew', padx=(10, 0))
        ttk.Label(right_col, text="> SYSTEM DIAGNOSTICS & LOGS", font=('Courier', 12, 'bold')).pack(anchor='w')
        self.log_text = scrolledtext.ScrolledText(right_col, width=20, bg='#000000', fg='#00FF00',
                                                  font=('Consolas', 10), wrap=tk.WORD, borderwidth=1, relief='solid')
        self.log_text.pack(fill='both', expand=True, pady=5)

        # State
        self.queue   = queue.Queue()
        self.running = True

        # Footer
        footer = ttk.Frame(self.root)
        footer.grid(row=2, column=0, sticky='ew', pady=(0, 10))
        keys_text = "[UP/DN]: Vol  [M]: Monitor  [E]: Ext Spkr  [I]: Mic  [B]: Audio  [ESC]: Fullscreen  |  Image: [ESC]: Close  [Q]: Close All  [S]: Save"
        ttk.Label(footer, text=keys_text, font=('Courier', 11, 'bold'), style='Hotkeys.TLabel').pack()

        # Key bindings — use bind (not bind_all) on root so popups can override with "break"
        self.root.bind('<Up>',     self.vol_up)
        self.root.bind('<Down>',   self.vol_down)
        self.root.bind('m',        self.sink_monitor)
        self.root.bind('M',        self.sink_monitor)
        self.root.bind('e',        self.sink_external)
        self.root.bind('E',        self.sink_external)
        self.root.bind('b',        self.show_audio_manager)
        self.root.bind('B',        self.show_audio_manager)
        self.root.bind('i',        self.show_source_selector)
        self.root.bind('I',        self.show_source_selector)
        self.root.bind('q',        lambda e: self.close_all_images())
        self.root.bind('Q',        lambda e: self.close_all_images())
        self.root.bind('<Escape>', self.toggle_fullscreen)
        self.root.focus_force()

        self.log_thread = threading.Thread(target=self.read_logs, daemon=True)
        self.log_thread.start()
        self.root.after(100, self.update_ui)

    # ── Log pipeline ──────────────────────────────────────────────────────────

    def read_logs(self):
        process = subprocess.Popen(
            ['journalctl', '-u', 'grokbox', '-f', '-n', '0'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True
        )
        while self.running and process.stdout:
            line = process.stdout.readline()
            if line:
                self.queue.put(line.strip())

    def update_ui(self):
        try:
            while True:
                self.process_log_line(self.queue.get_nowait())
        except queue.Empty:
            pass
        if self.running:
            self.root.after(100, self.update_ui)

    def process_log_line(self, line):
        self.log_text.insert(tk.END, line + '\n')
        self.log_text.see(tk.END)

        match = re.search(r'\[(?:INFO|ERROR|DEBUG|WARNING)\]\s+(.*)', line)
        if not match:
            return
        content = match.group(1).strip()

        if "starts listening for 'Hey Jarvis'" in content:
            self.set_state("LISTENING", "#00FFCC")
            self.user_text.delete(1.0, tk.END)
            self.grok_text.delete(1.0, tk.END)
        elif "Wake word detected!" in content:
            self.set_state("WAKE WORD TRIGGERED", "#FF0000")
            self.user_text.delete(1.0, tk.END)
        elif "AssemblyAI streaming channel opened" in content:
            self.set_state("TRANSCRIBING AUDIO...", "#FF00FF")
        elif content.startswith("[Partial]:"):
            self.user_text.delete(1.0, tk.END)
            self.user_text.insert(tk.END, content.replace("[Partial]:", "").strip() + "...")
        elif content.startswith("[FINAL]"):
            self.user_text.delete(1.0, tk.END)
            self.user_text.insert(tk.END, content.replace("[FINAL]", "").strip())
        elif "Querying [" in content:
            model = re.search(r'Querying \[(.+?)\]', content)
            label = model.group(1) if model else "GROK"
            self.set_state(f"QUERYING {label}...", "#FFFF00")
        elif content.startswith("Grok responded in"):
            self.set_state("SYSTEM RESPONDING", "#00FF00")
            m = re.search(r'Grok responded in [\d.]+s:\s+(.*)', content)
            if m:
                self.grok_text.delete(1.0, tk.END)
                self.grok_text.insert(tk.END, m.group(1))
        elif content.startswith("Kokoro generated TTS"):
            self.set_state("PLAYING AUDIO OUTPUT", "#00FF00")
        elif content.startswith("[SHOW_IMAGE]"):
            # Parse: [SHOW_IMAGE] /path/to/file.jpg
            try:
                img_path = content.replace("[SHOW_IMAGE]", "").strip().split("|")[0].strip()
                self.show_image_overlay(img_path)
            except Exception as ex:
                self.process_log_line(f"[ERROR] Image overlay failed: {ex}")
        elif content.startswith("[CLOSE_IMAGES]"):
            self.close_all_images()

    def set_state(self, text, color):
        self.status_text.config(text=f"STATUS: {text}")
        self.status_indicator.config(foreground=color)

    def show_image_overlay(self, img_path):
        """Display an image in a window on the right half of the screen.
        Keys: ESC=close this image, Q=close all images, S=save to ~/Pictures"""
        if not os.path.exists(img_path):
            self.process_log_line(f"[ERROR] Image not found: {img_path}")
            return

        if not hasattr(self, '_image_windows'):
            self._image_windows = []

        win_h = int(self.screen_height * 0.75)
        win_w = self.half_width

        # Stack windows with slight offset
        offset = len(self._image_windows) * 30
        x_pos = self.half_width + (offset % 90)
        y_pos = 50 + (offset % 120)

        overlay = tk.Toplevel(self.root)
        overlay.title(os.path.basename(img_path))
        overlay.configure(bg='#000000')
        overlay.geometry(f"{win_w}x{win_h}+{x_pos}+{y_pos}")
        overlay.lift()
        overlay.focus_force()

        # Store the source path on the window for saving
        overlay._img_source = img_path

        try:
            img = Image.open(img_path)
            img.thumbnail((win_w - 20, win_h - 40), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)

            label = tk.Label(overlay, image=photo, bg='#000000')
            label.image = photo  # prevent GC
            label.pack(expand=True, pady=10)
        except Exception as ex:
            tk.Label(overlay, text=f"Could not load image:\n{ex}",
                     fg='#FF0000', bg='#000000', font=('Courier', 16)).pack(expand=True)

        self._image_windows.append(overlay)
        overlay.protocol("WM_DELETE_WINDOW", lambda: self._close_image(overlay))
        overlay.bind('<Escape>', lambda e: self._close_image(overlay))
        overlay.bind('q', lambda e: self.close_all_images())
        overlay.bind('Q', lambda e: self.close_all_images())
        overlay.bind('s', lambda e: self._save_image(overlay))
        overlay.bind('S', lambda e: self._save_image(overlay))

    def _close_image(self, win):
        if win in self._image_windows:
            self._image_windows.remove(win)
        try:
            win.destroy()
        except Exception:
            pass

    def close_all_images(self):
        if not hasattr(self, '_image_windows'):
            return
        for win in list(self._image_windows):
            try:
                win.destroy()
            except Exception:
                pass
        self._image_windows.clear()
        self.process_log_line("[INFO] All images closed")

    def _save_image(self, win):
        src = getattr(win, '_img_source', None)
        if not src or not os.path.exists(src):
            return
        save_dir = os.path.expanduser("~/Pictures")
        os.makedirs(save_dir, exist_ok=True)
        import shutil
        dest = os.path.join(save_dir, os.path.basename(src))
        shutil.copy2(src, dest)
        self.process_log_line(f"[INFO] Image saved to {dest}")

    # ── Volume / sink shortcuts ────────────────────────────────────────────────

    def vol_up(self, e=None):
        subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"], env=self.pw_env)
        subprocess.run(["amixer", "-c", "0", "set", "PCM Playback Volume", "5%+"], capture_output=True)
        self.process_log_line("[INFO] 🔊 Volume UP")

    def vol_down(self, e=None):
        subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"], env=self.pw_env)
        subprocess.run(["amixer", "-c", "0", "set", "PCM Playback Volume", "5%-"], capture_output=True)
        self.process_log_line("[INFO] 🔉 Volume DOWN")

    def sink_monitor(self, e=None):
        try:
            cmd = "XDG_RUNTIME_DIR=/run/user/1000 wpctl status | awk '/Sinks:/,/(Sources|Filters|Video):/' | grep -i HDMI | grep -oP '\\b\\d+\\b' | head -n 1"
            sink = subprocess.check_output(cmd, shell=True, env=self.pw_env).decode().strip()
            if sink:
                subprocess.run(["wpctl", "set-default", sink], env=self.pw_env)
                self.process_log_line(f"[INFO] 🖥️ HDMI Audio ON (Node {sink})")
            else:
                self.process_log_line("[ERROR] Monitor/HDMI sink not found.")
        except Exception as ex:
            self.process_log_line(f"[ERROR] Sink switch failed: {ex}")

    def sink_external(self, e=None):
        try:
            cmd = "XDG_RUNTIME_DIR=/run/user/1000 wpctl status | awk '/Sinks:/,/(Sources|Filters|Video):/' | grep -i 'blue\\|party' | grep -oP '\\b\\d+\\b' | head -n 1"
            sink = subprocess.check_output(cmd, shell=True, env=self.pw_env).decode().strip()
            if sink:
                subprocess.run(["wpctl", "set-default", sink], env=self.pw_env)
                self.process_log_line(f"[INFO] 🎵 External BT Speaker ON (Node {sink})")
            else:
                self.process_log_line("[ERROR] External speaker not found (is BBP connected?)")
        except Exception as ex:
            self.process_log_line(f"[ERROR] Sink switch failed: {ex}")

    def toggle_fullscreen(self, e=None):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.root.geometry(f"{self.screen_width}x{self.screen_height}+0+0")
        else:
            self.root.geometry(f"{self.half_width}x{self.window_height}+0+0")

    # ── Quick mic selector (I key) ────────────────────────────────────────────

    def show_source_selector(self, e=None):
        if self.src_window and self.src_window.winfo_exists():
            self.src_window.lift(); self.src_window.focus_force(); return

        win = tk.Toplevel(self.root)
        self.src_window = win
        win.title("Quick Mic Selector")
        win.configure(bg='#000000')
        win.transient(self.root)
        win.grab_set()

        w = int(self.screen_width * 0.45)
        h = int(self.window_height * 0.38)
        win.geometry(f"{w}x{h}+{(self.screen_width-w)//2}+{(self.window_height-h)//2}")

        style = ttk.Style()
        style.configure('Src.TLabel',    background='#000000', foreground='#00FFCC', font=('Courier', 13, 'bold'))
        style.configure('SrcSub.TLabel', background='#000000', foreground='#888888', font=('Courier', 10))

        ttk.Label(win, text="QUICK MIC INPUT", style='Src.TLabel').pack(pady=(14, 3))
        ttk.Label(win, text="[ENTER] Apply & restart daemon   [ESC] Close", style='SrcSub.TLabel').pack()

        self.src_status_var = tk.StringVar(value="Select source then press ENTER.")
        ttk.Label(win, textvariable=self.src_status_var, style='SrcSub.TLabel').pack(pady=(2, 5))

        lf = tk.Frame(win, bg='#000000')
        lf.pack(fill='both', expand=True, padx=14, pady=(0, 8))
        sb = tk.Scrollbar(lf, orient='vertical')
        self.src_listbox = tk.Listbox(lf, bg='#112240', fg='#e6f1ff', font=('Courier', 12),
                                      selectbackground='#00FFCC', selectforeground='#000000',
                                      activestyle='dotbox', yscrollcommand=sb.set)
        sb.config(command=self.src_listbox.yview)
        sb.pack(side='right', fill='y')
        self.src_listbox.pack(side='left', fill='both', expand=True)

        self.src_devices = self._get_pw_nodes("Sources")
        default_idx = 0
        for i, s in enumerate(self.src_devices):
            marker = "★ " if s["default"] else "  "
            self.src_listbox.insert(tk.END, f"{marker}{s['name']}  [{self._dev_type(s['name'])}]  node {s['id']}")
            if s["default"]:
                default_idx = i
        if not self.src_devices:
            self.src_listbox.insert(tk.END, "  No audio sources found.")
        else:
            self.src_listbox.select_set(default_idx)

        self.src_listbox.focus_set()

        def _close(ev=None):
            win.destroy()
            return "break"

        win.bind('<Escape>', _close)
        win.bind('<Return>', self._apply_src)

    def _apply_src(self, e=None):
        sel = self.src_listbox.curselection()
        if not sel or not self.src_devices or sel[0] >= len(self.src_devices):
            return
        s = self.src_devices[sel[0]]
        subprocess.run(["wpctl", "set-default", s["id"]], env=self.pw_env)
        self.process_log_line(f"[INFO] 🎤 Mic → {s['name']} (node {s['id']})")
        self.src_status_var.set(f"Applying {s['name']}... restarting daemon")
        self.src_window.update_idletasks()
        subprocess.run(["systemctl", "restart", "grokbox"])
        self.process_log_line("[INFO] 🔄 grokbox restarted with new mic")
        self.src_window.destroy()

    # ── Audio I/O Manager (B key) ─────────────────────────────────────────────

    def show_audio_manager(self, e=None):
        if self.audio_mgr_win and self.audio_mgr_win.winfo_exists():
            self.audio_mgr_win.lift(); self.audio_mgr_win.focus_force(); return

        win = tk.Toplevel(self.root)
        self.audio_mgr_win = win
        win.title("Audio I/O Manager")
        win.configure(bg='#000000')
        win.transient(self.root)
        win.grab_set()

        w = int(self.screen_width * 0.82)
        h = int(self.window_height * 0.78)
        win.geometry(f"{w}x{h}+{(self.screen_width-w)//2}+{(self.window_height-h)//2}")

        style = ttk.Style()
        style.configure('AM.TLabel',    background='#000000', foreground='#00FFCC', font=('Courier', 14, 'bold'))
        style.configure('AMSec.TLabel', background='#000000', foreground='#FFD700', font=('Courier', 11, 'bold'))
        style.configure('AMSub.TLabel', background='#000000', foreground='#777777', font=('Courier', 10))

        ttk.Label(win, text="AUDIO  I/O  MANAGER", style='AM.TLabel').pack(pady=(12, 2))

        self.am_status = tk.StringVar(value="Loading...")
        ttk.Label(win, textvariable=self.am_status, style='AMSub.TLabel').pack()

        # ── Top: Outputs | Inputs ──────────────────────────────────────────────
        top = tk.Frame(win, bg='#000000')
        top.pack(fill='both', expand=True, padx=12, pady=(8, 4))
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=1)
        top.grid_rowconfigure(1, weight=1)

        ttk.Label(top, text="▶  OUTPUTS  (sinks)", style='AMSec.TLabel').grid(
            row=0, column=0, sticky='w', padx=(0, 8), pady=(0, 2))
        ttk.Label(top, text="◀  INPUTS  (sources)", style='AMSec.TLabel').grid(
            row=0, column=1, sticky='w', padx=(8, 0), pady=(0, 2))

        out_frame = tk.Frame(top, bg='#000000')
        out_frame.grid(row=1, column=0, sticky='nsew', padx=(0, 8))
        out_sb = tk.Scrollbar(out_frame, orient='vertical')
        self.am_out_lb = tk.Listbox(out_frame, bg='#08162a', fg='#64ffda', font=('Courier', 11),
                                    selectbackground='#00FFCC', selectforeground='#000000',
                                    activestyle='dotbox', yscrollcommand=out_sb.set)
        out_sb.config(command=self.am_out_lb.yview)
        out_sb.pack(side='right', fill='y')
        self.am_out_lb.pack(side='left', fill='both', expand=True)

        in_frame = tk.Frame(top, bg='#000000')
        in_frame.grid(row=1, column=1, sticky='nsew', padx=(8, 0))
        in_sb = tk.Scrollbar(in_frame, orient='vertical')
        self.am_in_lb = tk.Listbox(in_frame, bg='#08162a', fg='#ff79c6', font=('Courier', 11),
                                   selectbackground='#FF79C6', selectforeground='#000000',
                                   activestyle='dotbox', yscrollcommand=in_sb.set)
        in_sb.config(command=self.am_in_lb.yview)
        in_sb.pack(side='right', fill='y')
        self.am_in_lb.pack(side='left', fill='both', expand=True)

        # ── Bottom: Bluetooth devices ──────────────────────────────────────────
        ttk.Label(win, text="⬡  BLUETOOTH  DEVICES", style='AMSec.TLabel').pack(
            anchor='w', padx=12, pady=(6, 2))

        bt_frame = tk.Frame(win, bg='#000000')
        bt_frame.pack(fill='x', padx=12, pady=(0, 4))
        bt_sb = tk.Scrollbar(bt_frame, orient='vertical')
        self.am_bt_lb = tk.Listbox(bt_frame, bg='#112240', fg='#e6f1ff', font=('Courier', 11),
                                   selectbackground='#FFD700', selectforeground='#000000',
                                   height=5, activestyle='dotbox', yscrollcommand=bt_sb.set)
        bt_sb.config(command=self.am_bt_lb.yview)
        bt_sb.pack(side='right', fill='y')
        self.am_bt_lb.pack(side='left', fill='both', expand=True)

        # ── Footer hints ───────────────────────────────────────────────────────
        hints = ("[ENTER] Set default   [TAB] Switch panel   "
                 "[C] BT Connect   [D] Disconnect   [R] Remove   [S] Scan   [ESC] Close")
        ttk.Label(win, text=hints, style='AMSub.TLabel').pack(pady=(2, 8))

        # Internal state
        self.am_sinks   = []
        self.am_sources = []
        self.am_bt_devs = []
        self.am_focus   = 'out'   # 'out' | 'in' | 'bt'

        # Focus tracking
        self.am_out_lb.bind('<FocusIn>', lambda ev: setattr(self, 'am_focus', 'out'))
        self.am_in_lb.bind('<FocusIn>',  lambda ev: setattr(self, 'am_focus', 'in'))
        self.am_bt_lb.bind('<FocusIn>',  lambda ev: setattr(self, 'am_focus', 'bt'))
        self.am_out_lb.bind('<Return>', self._am_apply)
        self.am_in_lb.bind('<Return>',  self._am_apply)
        self.am_bt_lb.bind('<Return>',  self._am_bt_connect)

        # Window-level bindings — return "break" to stop propagation to root
        def _esc(ev=None):
            win.destroy()
            return "break"

        def _tab(ev=None):
            cycle = {'out': self.am_in_lb,  'in': self.am_bt_lb, 'bt': self.am_out_lb}
            cycle[self.am_focus].focus_set()
            return "break"

        win.bind('<Escape>', _esc)
        win.bind('<Return>', self._am_apply)
        win.bind('<Tab>',    _tab)
        win.bind('c', self._am_bt_connect);   win.bind('C', self._am_bt_connect)
        win.bind('d', self._am_bt_disconnect); win.bind('D', self._am_bt_disconnect)
        win.bind('r', self._am_bt_remove);     win.bind('R', self._am_bt_remove)
        win.bind('s', self._am_scan);          win.bind('S', self._am_scan)

        self.am_out_lb.focus_set()
        threading.Thread(target=self._am_refresh, daemon=True).start()

    def _am_refresh(self):
        """Reload all three lists from live system state."""
        try:
            self.am_status.set("Refreshing...")

            sinks = self._get_pw_nodes("Sinks")
            self.am_sinks = sinks
            self.am_out_lb.delete(0, tk.END)
            default_out = 0
            for i, s in enumerate(sinks):
                marker = "★ " if s["default"] else "  "
                self.am_out_lb.insert(tk.END, f"{marker}{s['name']}  [{self._dev_type(s['name'])}]  node {s['id']}")
                if s["default"]:
                    default_out = i
            if sinks:
                self.am_out_lb.select_set(default_out)
            else:
                self.am_out_lb.insert(tk.END, "  No sinks found")

            sources = self._get_pw_nodes("Sources")
            self.am_sources = sources
            self.am_in_lb.delete(0, tk.END)
            default_in = 0
            for i, s in enumerate(sources):
                marker = "★ " if s["default"] else "  "
                self.am_in_lb.insert(tk.END, f"{marker}{s['name']}  [{self._dev_type(s['name'])}]  node {s['id']}")
                if s["default"]:
                    default_in = i
            if sources:
                self.am_in_lb.select_set(default_in)
            else:
                self.am_in_lb.insert(tk.END, "  No sources found")

            bt_devs = self._get_bt_devices()
            self.am_bt_devs = bt_devs
            self.am_bt_lb.delete(0, tk.END)
            for d in bt_devs:
                dot   = "●" if d["connected"] else "○"
                state = "CONNECTED" if d["connected"] else ("paired" if d["paired"] else "known")
                trust = " [T]" if d["trusted"] else ""
                self.am_bt_lb.insert(tk.END, f"  {dot} {d['name']}{trust}   {d['mac']}   [{state}]")
            if not bt_devs:
                self.am_bt_lb.insert(tk.END, "  No paired BT devices")

            self.am_status.set(
                f"{len(sinks)} outputs   {len(sources)} inputs   {len(bt_devs)} BT devices  "
                "│  [ENTER] set default   [TAB] switch panel   [C/D/R/S] BT ops"
            )
        except Exception as ex:
            self.am_status.set(f"Refresh error: {ex}")

    def _am_apply(self, e=None):
        focus = self.am_focus
        if focus == 'out':
            sel = self.am_out_lb.curselection()
            if not sel or sel[0] >= len(self.am_sinks): return
            s = self.am_sinks[sel[0]]
            subprocess.run(["wpctl", "set-default", s["id"]], env=self.pw_env)
            self.process_log_line(f"[INFO] 🔊 Output → {s['name']} (node {s['id']})")
            self.am_status.set(f"Output set: {s['name']}")
            threading.Thread(target=self._am_refresh, daemon=True).start()
        elif focus == 'in':
            sel = self.am_in_lb.curselection()
            if not sel or sel[0] >= len(self.am_sources): return
            s = self.am_sources[sel[0]]
            subprocess.run(["wpctl", "set-default", s["id"]], env=self.pw_env)
            self.process_log_line(f"[INFO] 🎤 Input → {s['name']} (node {s['id']})")
            self.am_status.set(f"Input set: {s['name']} — restarting daemon...")
            self.audio_mgr_win.update_idletasks()
            subprocess.run(["systemctl", "restart", "grokbox"])
            self.process_log_line("[INFO] 🔄 grokbox restarted with new mic")
            threading.Thread(target=self._am_refresh, daemon=True).start()
        elif focus == 'bt':
            self._am_bt_connect()

    def _am_bt_connect(self, e=None):
        self.am_bt_lb.focus_set()
        sel = self.am_bt_lb.curselection()
        if not sel or sel[0] >= len(self.am_bt_devs): return
        d = self.am_bt_devs[sel[0]]
        if d["connected"]:
            self.am_status.set(f"Already connected: {d['name']}")
            return
        self.am_status.set(f"Connecting to {d['name']}...")
        self.process_log_line(f"[INFO] 🔄 Connecting {d['name']} ({d['mac']})...")
        threading.Thread(target=self._am_do_connect, args=(d["mac"], d["name"]), daemon=True).start()

    def _am_do_connect(self, mac, name):
        try:
            subprocess.run(["bluetoothctl", "trust",   mac], env=self.pw_env, capture_output=True)
            subprocess.run(["bluetoothctl", "pair",    mac], env=self.pw_env, capture_output=True)
            subprocess.run(["bluetoothctl", "connect", mac], env=self.pw_env, capture_output=True)
            time.sleep(2)
            info = subprocess.check_output(["bluetoothctl", "info", mac], text=True, env=self.pw_env)
            if "Connected: yes" in info:
                self.process_log_line(f"[INFO] ✅ Connected: {name}")
                # Auto-route to this sink if it appears in PipeWire
                time.sleep(1)
                sinks = self._get_pw_nodes("Sinks")
                for s in sinks:
                    if any(w.lower() in s["name"].lower() for w in name.split() if len(w) > 3):
                        subprocess.run(["wpctl", "set-default", s["id"]], env=self.pw_env)
                        self.process_log_line(f"[INFO] 🔊 Auto-routed output → {s['name']}")
                        break
            else:
                self.process_log_line(f"[ERROR] ❌ Connect failed for {name}")
        except Exception as ex:
            self.process_log_line(f"[ERROR] ❌ BT connect exception: {ex}")
        finally:
            threading.Thread(target=self._am_refresh, daemon=True).start()

    def _am_bt_disconnect(self, e=None):
        sel = self.am_bt_lb.curselection()
        if not sel or sel[0] >= len(self.am_bt_devs): return
        d = self.am_bt_devs[sel[0]]
        self.am_status.set(f"Disconnecting {d['name']}...")
        def _go():
            subprocess.run(["bluetoothctl", "disconnect", d["mac"]], env=self.pw_env, capture_output=True)
            self.process_log_line(f"[INFO] 🔌 Disconnected: {d['name']}")
            threading.Thread(target=self._am_refresh, daemon=True).start()
        threading.Thread(target=_go, daemon=True).start()

    def _am_bt_remove(self, e=None):
        sel = self.am_bt_lb.curselection()
        if not sel or sel[0] >= len(self.am_bt_devs): return
        d = self.am_bt_devs[sel[0]]
        self.am_status.set(f"Removing {d['name']}...")
        def _go():
            subprocess.run(["bluetoothctl", "remove", d["mac"]], env=self.pw_env, capture_output=True)
            self.process_log_line(f"[INFO] 🗑️ Removed: {d['name']}")
            threading.Thread(target=self._am_refresh, daemon=True).start()
        threading.Thread(target=_go, daemon=True).start()

    def _am_scan(self, e=None):
        self.am_status.set("Scanning for BT devices (10s)...")
        def _go():
            subprocess.run(["bluetoothctl", "--timeout", "10", "scan", "on"],
                           capture_output=True, env=self.pw_env)
            threading.Thread(target=self._am_refresh, daemon=True).start()
        threading.Thread(target=_go, daemon=True).start()

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _get_pw_nodes(self, section):
        """Parse wpctl status for Sinks or Sources. Returns list of {id, name, default}."""
        nodes = []
        try:
            output = subprocess.check_output(
                ["wpctl", "status"], env=self.pw_env,
                universal_newlines=True, stderr=subprocess.DEVNULL
            )
            active = False
            for line in output.splitlines():
                if f"─ {section}:" in line:
                    active = True; continue
                if active:
                    if not line.strip() or any(x in line for x in
                            ("Filters:", "Streams:", "Video", "Settings", "Devices:")):
                        active = False; continue
                    if ("├─" in line or "└─" in line) and f"{section}:" not in line:
                        active = False; continue
                    m = re.search(r'(\*?)\s+(\d+)\.\s+(.+?)\s+\[', line)
                    if m:
                        nodes.append({"id": m.group(2), "name": m.group(3).strip(),
                                      "default": "*" in line})
        except Exception:
            pass
        return nodes

    def _get_bt_devices(self):
        """Returns list of {mac, name, connected, paired, trusted}."""
        devices = []
        try:
            out = subprocess.check_output(["bluetoothctl", "devices"],
                                          universal_newlines=True, env=self.pw_env)
            for line in out.splitlines():
                if not line.startswith("Device"):
                    continue
                parts = line.split(" ", 2)
                if len(parts) < 3:
                    continue
                mac, name = parts[1], parts[2]
                info = subprocess.check_output(["bluetoothctl", "info", mac],
                                               universal_newlines=True, env=self.pw_env)
                devices.append({
                    "mac": mac, "name": name,
                    "connected": "Connected: yes" in info,
                    "paired":    "Paired: yes"    in info,
                    "trusted":   "Trusted: yes"   in info,
                })
        except Exception as ex:
            self.process_log_line(f"[ERROR] BT device list failed: {ex}")
        return devices

    def _get_daemon_model(self):
        """Read the XAI_MODEL from the daemon source."""
        try:
            with open("/Code/grokbox/scripts/grokbox_daemon.py") as f:
                for line in f:
                    if line.startswith("XAI_MODEL"):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
        return "unknown"

    def _dev_type(self, name):
        n = name.lower()
        if any(x in n for x in ('hdmi', 'displayport')):  return 'HDMI'
        if any(x in n for x in ('usb', 'composite', 'snowball')): return 'USB'
        if any(x in n for x in ('dummy', 'virtual', 'null')): return 'VIRT'
        return 'ALSA'

    # Keep old name as alias so connect_speaker.sh / any external refs still work
    def _get_audio_sources(self):
        return self._get_pw_nodes("Sources")


if __name__ == "__main__":
    root = tk.Tk()
    app  = GrokBoxGUI(root)
    root.mainloop()
