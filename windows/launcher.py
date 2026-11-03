"""Windows setup and login supervisor for the existing Social Video Analyzer services.

Credentials stay on this computer, encrypted with Windows DPAPI CurrentUser.
No credentials are accepted as command-line arguments or written to profiles.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
import secrets
import uuid
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".insta-analyzer"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
RUN_NAME = "InstaAnalyzer"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Settings:
    tunnel_id: str
    runtime_key: str
    gemini_key: str
    backend_port: int = 18002
    health_port: int = 18080
    model: str = "gemini-3.6-flash"
    auto_start: bool = True
    mode: str = "chatgpt"
    backend_key: str = field(default_factory=lambda: secrets.token_urlsafe(32))

    def validate(self):
        if len(self.backend_key) < 32:
            raise ValueError("The internal backend credential must have at least 32 characters.")
        if self.mode not in {"local", "chatgpt"}:
            raise ValueError("Choose local or ChatGPT mode.")
        if self.mode == "chatgpt" and not re.fullmatch(r"tunnel_[a-fA-F0-9]{32}", self.tunnel_id):
            raise ValueError("Enter the tunnel ID from OpenAI Platform (tunnel_...).")
        if len(self.gemini_key.strip()) < 10 or (self.mode == "chatgpt" and len(self.runtime_key.strip()) < 10):
            raise ValueError("Enter your Gemini API key (and a runtime key for ChatGPT mode).")
        for port in [self.backend_port, self.health_port]:
            if not isinstance(port, int) or not 1024 <= port <= 65535:
                raise ValueError("Ports must be whole numbers between 1024 and 65535.")
        if self.backend_port == self.health_port:
            raise ValueError("Backend and tunnel status ports must differ.")
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", self.model):
            raise ValueError("Enter a valid Gemini model ID.")


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data: bytes, *, decrypt=False) -> bytes:
    """Use CurrentUser DPAPI, explicitly disallowing interactive OS prompts."""
    if os.name != "nt":
        raise RuntimeError("Credential storage requires Windows.")
    backing = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    api = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError("Windows could not unlock these credentials for this user.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def save_settings(settings: Settings, state=STATE):
    settings.validate()
    state.mkdir(parents=True, exist_ok=True)
    encrypted = crypt(json.dumps(asdict(settings)).encode("utf-8"))
    temporary = state / "credentials.new"
    temporary.write_bytes(encrypted)
    temporary.replace(state / "credentials.dpapi")


def load_settings(state=STATE) -> Settings:
    data = json.loads(crypt((state / "credentials.dpapi").read_bytes(), decrypt=True))
    settings = Settings(**data)
    settings.validate()
    if "backend_key" not in data:
        save_settings(settings, state)
    return settings


def startup_command():
    executable = PYTHON.with_name("pythonw.exe")
    return subprocess.list2cmdline([str(executable), str(Path(__file__).resolve()), "supervise"])


def configure_autostart(enabled: bool):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def is_running(state=STATE):
    """Probe the owned lock rather than trusting a possibly reused PID."""
    import msvcrt
    state.mkdir(parents=True, exist_ok=True)
    with (state / "supervisor.lock").open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return True
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    return False


def start_supervisor():
    if is_running():
        return
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "stop").unlink(missing_ok=True)
    subprocess.Popen([str(PYTHON.with_name("pythonw.exe")), str(Path(__file__).resolve()), "supervise"],
                     cwd=ROOT, creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def stop_supervisor(timeout=15):
    if not is_running():
        return
    (STATE / "stop").touch()
    deadline = time.monotonic() + timeout
    while is_running() and time.monotonic() < deadline:
        time.sleep(0.25)
    if is_running():
        raise RuntimeError("The existing runtime is still stopping. Try again shortly.")


def http_ok(port: int, path: str):
    # Ignore global HTTP proxies for loopback health checks.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def assert_free_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            raise RuntimeError(f"Port {port} is occupied. Close the old manual backend/tunnel windows first.") from None


def write_status(message, **extra):
    STATE.mkdir(parents=True, exist_ok=True)
    temp = STATE / "status.new"
    temp.write_text(json.dumps({"message": message, "updated": time.time(), **extra}), encoding="utf-8")
    for attempt in range(10):
        try:
            temp.replace(STATE / "status.json")
            return
        except PermissionError:
            # A Windows reader or virus scanner may briefly deny delete sharing.
            time.sleep(0.05)


def read_status():
    if not is_running():
        try:
            message = json.loads((STATE / "status.json").read_text(encoding="utf-8"))["message"]
            if message.startswith("Setup required"):
                return message
        except (OSError, ValueError):
            pass
        return "Stopped"
    try:
        return json.loads((STATE / "status.json").read_text(encoding="utf-8"))["message"]
    except (OSError, ValueError):
        return "Starting..."


def safe_logger(settings):
    logger = logging.getLogger("insta-launcher")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(STATE / "runtime.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    class Redact(logging.Filter):
        def filter(self, record):
            message = record.getMessage()
            for secret in [settings.runtime_key, settings.gemini_key, settings.backend_key]:
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            record.msg, record.args = message, ()
            return True
    handler.addFilter(Redact())
    logger.addHandler(handler)
    return logger


def spawn(command, env, logger, label):
    import win32job
    job = win32job.CreateJobObject(None, "InstaAnalyzer-" + uuid.uuid4().hex)
    information = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    information["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, information)
    child = subprocess.Popen(command, cwd=ROOT, env=env, creationflags=CREATE_NO_WINDOW,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
    try:
        win32job.AssignProcessToJobObject(job, child._handle)
    except Exception:
        child.kill()
        child.wait(timeout=5)
        job.Close()
        raise RuntimeError("Windows could not isolate the background process for safe shutdown.") from None
    child._insta_job = job
    def pump():
        with child.stdout:
            for line in child.stdout:
                logger.info("%s %s", label, line.rstrip())
    threading.Thread(target=pump, daemon=True).start()
    return child


def terminate_owned(child):
    if child is None:
        return
    # The Windows job contains only this child and its descendants, including stdio.
    job = getattr(child, "_insta_job", None)
    if job is not None:
        import win32job
        try:
            win32job.TerminateJobObject(job, 0)
        finally:
            job.Close()
            child._insta_job = None
    if child.poll() is None:
        child.kill()
    child.wait(timeout=5)


def wait_ready(child, port, path, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not (STATE / "stop").exists():
        if child.poll() is not None:
            raise RuntimeError("Service exited during startup. Check the local runtime log.")
        if http_ok(port, path):
            return
        time.sleep(1)
    raise RuntimeError("Service did not become ready. Check the key, permissions, and local runtime log.")


def supervise():
    import msvcrt
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "supervisor.lock").open("a+b") as lock:
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        backend = tunnel = None
        try:
            settings = load_settings()
            logger = safe_logger(settings)
            env = dict(os.environ, GEMINI_API_KEY=settings.gemini_key,
                       GEMINI_MODEL=settings.model, CONTROL_PLANE_API_KEY=settings.runtime_key,
                       BACKEND_API_KEY=settings.backend_key,
                       API_BASE_URL=f"http://127.0.0.1:{settings.backend_port}", PYTHONUTF8="1")
            backend_env = dict(env)
            backend_env.pop("CONTROL_PLANE_API_KEY", None)
            tunnel_env = dict(env)
            tunnel_env.pop("GEMINI_API_KEY", None)
            client = ROOT / ".tools" / "tunnel-client" / "tunnel-client.exe"
            profiles = STATE / "profiles"
            # Generate only this launcher's profile; do not overwrite the manual profile.
            command = f'"{PYTHON.as_posix()}" "{(ROOT / "mcp-server" / "mcp_sse_server.py").as_posix()}" --stdio'
            if settings.mode == "chatgpt":
                result = subprocess.run([str(client), "init", "--sample", "sample_mcp_stdio_local",
                                         "--profile", "automatic", "--profile-dir", str(profiles), "--force",
                                         "--tunnel-id", settings.tunnel_id, "--mcp-command", command,
                                         "--health-listen-addr", f"127.0.0.1:{settings.health_port}"],
                                        env=env, cwd=ROOT, creationflags=CREATE_NO_WINDOW,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                if result.returncode:
                    raise RuntimeError("Could not create the tunnel profile. Run Setup again.")
            delay = 2
            while not (STATE / "stop").exists():
                try:
                    write_status("Starting backend...")
                    assert_free_port(settings.backend_port)
                    if settings.mode == "chatgpt":
                        assert_free_port(settings.health_port)
                    backend = spawn([str(PYTHON), "-m", "uvicorn", "app.main:app", "--app-dir", "backend",
                                     "--host", "127.0.0.1", "--port", str(settings.backend_port), "--no-access-log"],
                                    backend_env, logger, "backend")
                    wait_ready(backend, settings.backend_port, "/health")
                    if settings.mode == "chatgpt":
                        write_status("Connecting secure tunnel...")
                        tunnel = spawn([str(client), "run", "--profile", "automatic", "--profile-dir", str(profiles)],
                                       tunnel_env, logger, "tunnel")
                        wait_ready(tunnel, settings.health_port, "/readyz", seconds=90)
                        write_status("Ready — Social Video Analyzer is connected")
                    else:
                        write_status("Ready — local MCP clients can connect")
                    delay = 2
                    while not (STATE / "stop").exists():
                        if backend.poll() is not None or (tunnel is not None and tunnel.poll() is not None):
                            raise RuntimeError("A service stopped; restarting automatically.")
                        if settings.mode == "local":
                            write_status("Ready — local MCP clients can connect")
                        elif http_ok(settings.health_port, "/readyz"):
                            write_status("Ready — Social Video Analyzer is connected")
                        else:
                            write_status("Tunnel reconnecting; checking network and account access...")
                        time.sleep(3)
                except Exception as exc:
                    logger.warning("%s", exc)
                    write_status(str(exc))
                finally:
                    terminate_owned(tunnel)
                    terminate_owned(backend)
                    tunnel = backend = None
                for _ in range(delay):
                    if (STATE / "stop").exists():
                        break
                    time.sleep(1)
                delay = min(delay * 2, 60)
        except Exception as exc:
            if "logger" in locals():
                logger.warning("Setup failure: %s", exc)
            write_status("Setup required (" + type(exc).__name__ + "). Open Setup or check the local runtime log.")
        finally:
            terminate_owned(tunnel)
            terminate_owned(backend)
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def show_setup():
    import tkinter as tk
    from tkinter import ttk, messagebox
    import webbrowser
    window = tk.Tk()
    window.title("Social Video Analyzer — Setup & Status")
    window.geometry("650x820")
    window.minsize(650, 820)
    panel = ttk.Frame(window, padding=22)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="Social Video Analyzer", font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(panel, text="Enter your own credentials once. Windows encrypts them for your account.",
              wraplength=590).pack(anchor="w", pady=(5, 12))
    existing = None
    try:
        existing = load_settings()
    except (OSError, ValueError, TypeError):
        pass
    previous_tunnel = ""
    previous_gemini = ""
    if existing is None:
        profile = ROOT / ".tools" / "tunnel-profiles" / "insta-analyzer.yaml"
        if profile.exists():
            match = re.search(r'tunnel_id:\s*"?(tunnel_[a-fA-F0-9]{32})', profile.read_text(encoding="utf-8"))
            if match:
                previous_tunnel = match.group(1)
        from dotenv import dotenv_values
        previous_gemini = dotenv_values(ROOT / "backend" / ".env").get("GEMINI_API_KEY", "") or ""
    mode = tk.StringVar(value=existing.mode if existing else "local")
    ttk.Label(panel, text="Connection mode (local needs only Gemini)").pack(anchor="w")
    selector = ttk.Combobox(panel, textvariable=mode, values=["local", "chatgpt"], state="readonly")
    selector.pack(fill="x")
    variables = {}
    entries = {}
    for field, label, default, secret in [
        ("tunnel_id", "OpenAI tunnel ID", existing.tunnel_id if existing else previous_tunnel, False),
        ("runtime_key", "OpenAI tunnel runtime API key", "", True),
        ("gemini_key", "Google Gemini API key", "", True),
        ("model", "Gemini model", existing.model if existing else "gemini-3.6-flash", False),
        ("backend_port", "Backend port", str(existing.backend_port if existing else 18002), False),
    ]:
        ttk.Label(panel, text=label).pack(anchor="w", pady=(5, 1))
        variable = tk.StringVar(value=default)
        variables[field] = variable
        entries[field] = ttk.Entry(panel, textvariable=variable, show="•" if secret else "")
        entries[field].pack(fill="x")
    def update_mode(*args):
        for field in ["tunnel_id", "runtime_key"]:
            entries[field].configure(state="normal" if mode.get() == "chatgpt" else "disabled")
    selector.bind("<<ComboboxSelected>>", update_mode)
    update_mode()
    if existing:
        ttk.Label(panel, text="Leave key fields empty to keep your saved keys.").pack(anchor="w", pady=(3, 0))
    elif previous_gemini:
        ttk.Label(panel, text="Leave Gemini key empty to reuse your existing backend key.").pack(anchor="w", pady=(3, 0))
    auto = tk.BooleanVar(value=existing.auto_start if existing else True)
    ttk.Checkbutton(panel, text="Start automatically when I sign in to Windows", variable=auto).pack(anchor="w", pady=12)
    status = tk.StringVar(value=read_status())
    ttk.Label(panel, textvariable=status, wraplength=590).pack(anchor="w", pady=6)

    def save():
        nonlocal existing
        try:
            settings = Settings(
                tunnel_id=variables["tunnel_id"].get().strip(),
                runtime_key=variables["runtime_key"].get().strip() or (existing.runtime_key if existing else ""),
                gemini_key=variables["gemini_key"].get().strip() or (existing.gemini_key if existing else previous_gemini),
                model=variables["model"].get().strip(),
                backend_port=int(variables["backend_port"].get()),
                auto_start=auto.get(),
                mode=mode.get(),
            )
            settings.validate()
            stop_supervisor()
            save_settings(settings)
            export_client_configs(settings)
            configure_autostart(settings.auto_start)
            existing = settings
            variables["runtime_key"].set("")
            variables["gemini_key"].set("")
            start_supervisor()
            status.set("Saved securely. Starting services...")
        except Exception as exc:
            # Errors here are local validation/OS failures, never remote SDK messages.
            messagebox.showerror("Setup", str(exc), parent=window)

    buttons = ttk.Frame(panel)
    buttons.pack(fill="x", pady=8)
    ttk.Button(buttons, text="Save and start", command=save).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Stop", command=lambda: stop_supervisor()).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Open ChatGPT", command=lambda: webbrowser.open("https://chatgpt.com/")).pack(side="left")
    ttk.Button(buttons, text="Open logs", command=lambda: os.startfile(STATE)).pack(side="right")
    def open_clients():
        from clients import show_clients
        show_clients(ROOT, int(variables["backend_port"].get()), STATE)
    ttk.Button(panel, text="Set up AI applications (10 clients)", command=open_clients).pack(anchor="w")
    links = ttk.Frame(panel)
    links.pack(fill="x", pady=5)
    for title, url in [
        ("Create tunnel", "https://platform.openai.com/settings/organization/tunnels"),
        ("OpenAI runtime key", "https://platform.openai.com/settings/organization/api-keys"),
        ("Gemini key", "https://aistudio.google.com/apikey"),
    ]:
        ttk.Button(links, text=title, command=lambda u=url: webbrowser.open(u)).pack(side="left", padx=(0, 6))
    ttk.Label(panel, text="One-time ChatGPT setup: Add custom MCP server → Tunnel → your tunnel ID → No authentication. Install privately.",
              wraplength=590).pack(anchor="w", pady=10)
    def refresh():
        status.set(read_status())
        window.after(2000, refresh)
    window.after(2000, refresh)
    window.mainloop()


def export_client_configs(settings, destination=None):
    """Export mergeable client settings, containing no provider credentials."""
    destination = destination or STATE / "client-configs"
    destination.mkdir(parents=True, exist_ok=True)
    from clients import export_all
    export_all(ROOT, settings.backend_port, destination)
    (destination / "claude.json").write_text((destination / "claude-desktop.json").read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "supervise", "start", "stop", "status", "disable-autostart", "export-configs"], default="setup", nargs="?")
    action = parser.parse_args().action
    if action == "setup":
        show_setup()
    elif action == "supervise":
        supervise()
    elif action == "start":
        load_settings()
        start_supervisor()
    elif action == "export-configs":
        print(export_client_configs(load_settings()))
    elif action == "stop":
        stop_supervisor()
    elif action == "disable-autostart":
        configure_autostart(False)
        print("Automatic startup disabled. Your encrypted settings were kept.")
    else:
        print(read_status())


if __name__ == "__main__":
    main()
