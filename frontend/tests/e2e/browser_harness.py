"""Isolated Firefox, Django and Vite services for browser tests."""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from uuid import uuid4

import requests

ROOT = Path(__file__).resolve().parents[3]


def browser_test_password():
    return f"Test!{token_urlsafe(32)}"


def serve(database, port, configure=None):
    os.environ["DJANGO_SETTINGS_MODULE"] = "backend.settings"
    os.environ.update(DJANGO_ENV="development", API_KEY="", DB_NAME="",
                      DJANGO_THROTTLE_CACHE_URL="", CELERY_BROKER_URL="memory://")
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    from django.conf import settings
    from django.core.management import call_command

    settings.DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3", "NAME": database,
    }
    django.setup()
    if configure:
        configure()
    call_command("migrate", verbosity=0)
    call_command("runserver", f"127.0.0.1:{port}", use_reloader=False)


def free_ports(count):
    sockets = [socket.socket() for _ in range(count)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def wait_for(check):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            if result := check():
                return result
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise AssertionError(f"Timed out at check on line {check.__code__.co_firstlineno}")


class Browser:
    def __init__(self, origin, binary):
        self.origin = origin
        session = self.post("/session", capabilities={"alwaysMatch": {
            "browserName": "firefox",
            "moz:firefoxOptions": {"binary": binary, "args": ["-headless"]},
        }})
        self.prefix = f"/session/{session['sessionId']}"

    def post(self, path, **data):
        reply = requests.post(self.origin + path, json=data, timeout=30)
        assert reply.ok, reply.text[:300]
        return reply.json()["value"]

    def execute(self, script, *args):
        return self.post(f"{self.prefix}/execute/sync", script=script, args=list(args))

    def navigate(self, url):
        self.post(f"{self.prefix}/url", url=url)

    def tab(self):
        self.post(f"{self.prefix}/actions", actions=[{
            "type": "key", "id": "keyboard",
            "actions": [{"type": "keyDown", "value": "\ue004"}, {"type": "keyUp", "value": "\ue004"}],
        }])

    def send_key(self, value):
        self.post(f"{self.prefix}/actions", actions=[{
            "type": "key", "id": "keyboard",
            "actions": [{"type": "keyDown", "value": value}, {"type": "keyUp", "value": value}],
        }])

    def click(self, label):
        return self.execute("""
            const button = [...document.querySelectorAll('button')].find(
                el => el.textContent.trim() === arguments[0] && !el.disabled);
            if (button) button.click();
            return Boolean(button);
        """, label)

    def change(self, selector, value):
        self.execute("""
            const field = document.querySelector(arguments[0]);
            const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), 'value').set;
            setter.call(field, arguments[1]);
            field.dispatchEvent(new Event(field.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
        """, selector, value)

    def drop(self, name, content):
        self.execute("""
            const transfer = new DataTransfer();
            transfer.items.add(new File([arguments[1]], arguments[0], {type: 'text/csv'}));
            document.querySelector('.statement-drop').dispatchEvent(
                new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
        """, name, content)

    def step(self, label):
        return self.execute("return document.querySelector('#statement-step-title')?.textContent === arguments[0];", label)

    def close(self):
        requests.delete(self.origin + self.prefix, timeout=8)


def main(run_browser, server_script=__file__):
    firefox = os.getenv("FIREFOX_BIN") or shutil.which("firefox")
    geckodriver = os.getenv("GECKODRIVER_BIN") or shutil.which("geckodriver")
    if not firefox or not geckodriver:
        raise SystemExit("Install Firefox and geckodriver or set FIREFOX_BIN and GECKODRIVER_BIN.")
    api_port, vite_port, driver_port = free_ports(3)
    api, site, driver = [f"http://127.0.0.1:{port}" for port in (api_port, vite_port, driver_port)]
    processes = []
    with TemporaryDirectory(prefix="findash-browser-e2e-") as temporary:
        logs = {}

        def launch(service, command, cwd, **env):
            log = Path(temporary) / f"{service}.log"
            logs[service] = log
            with log.open("wb") as output:
                processes.append(subprocess.Popen(
                    command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                    env={**os.environ, **env},
                ))

        try:
            launch(
                "django", [sys.executable, server_script, "--serve", temporary + "/test.sqlite3", str(api_port)],
                ROOT, DJANGO_CORS_ALLOWED_ORIGINS=site,
            )
            launch("vite", ["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1",
                    "--port", str(vite_port), "--strictPort"], ROOT / "frontend", VITE_API_URL=api)
            launch("geckodriver", [geckodriver, "--port", str(driver_port), "--profile-root", temporary], ROOT)
            wait_for(lambda: requests.get(api + "/api/transactions/", timeout=2).status_code == 401)
            wait_for(lambda: requests.get(site + "/login", timeout=2).ok)
            wait_for(lambda: requests.get(driver + "/status", timeout=2).ok)
            run_browser(api, site, driver, firefox, temporary)
        except Exception:
            for service, log in logs.items():
                with log.open("rb") as output:
                    output.seek(max(0, log.stat().st_size - 4096))
                    tail = output.read().decode(errors="replace")
                if tail.strip():
                    print(f"\n--- {service} log ---\n{tail.rstrip()}", file=sys.stderr)
            raise
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    serve(*sys.argv[2:])
