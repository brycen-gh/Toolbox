"""Local folder sharing using Python's standard-library HTTP server."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from .result import ExecutionResult


class ShareHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        # Do not expose files outside the share through symlinks or junctions.
        target = Path(self.translate_path(self.path)).resolve()
        if not target.is_relative_to(Path(self.directory).resolve()):
            self.send_error(403, "Outside shared folder")
            return None
        if target.is_dir():
            for name in ("index.html", "index.htm"):
                if not (target / name).resolve().is_relative_to(Path(self.directory).resolve()):
                    self.send_error(403, "Outside shared folder")
                    return None
        return super().send_head()

    def log_message(self, format, *args):
        # Requests arrive on background threads, outside the action output UI.
        pass


class ToolsActions:
    def _start_share(self, parameters):
        if self._share_server is not None:
            return self._share_status({})
        directory = Path(parameters.get("directory", "./share"))
        if not directory.is_absolute():
            directory = self.base_dir / directory
        directory = directory.resolve()
        host = str(parameters.get("host", "0.0.0.0")).strip()
        port = int(parameters.get("port", 8000))
        if not 0 <= port <= 65535:
            raise ValueError("Share port must be between 0 and 65535")
        directory.mkdir(parents=True, exist_ok=True)
        try:
            server = ThreadingHTTPServer((host, port), partial(ShareHandler, directory=str(directory)))
        except OSError as exc:
            return ExecutionResult([f"Could not start folder sharing: {exc}"], 1)
        thread = threading.Thread(target=server.serve_forever, name="folder-share", daemon=True)
        self._share_server = server
        self._share_thread = thread
        self._share_directory = directory
        thread.start()
        return self._share_status({})

    def _share_status(self, _parameters):
        if self._share_server is None:
            return ExecutionResult(["Folder sharing is stopped."])
        host, port = self._share_server.server_address[:2]
        address = "127.0.0.1" if host == "0.0.0.0" else host
        return ExecutionResult([
            f"Sharing {self._share_directory}",
            f"Open http://{address}:{port}/ on this computer.",
            f"Listening on {host}:{port}. Other computers can use http://<this-computer-IP>:{port}/ if the firewall allows it.",
            "HTTP downloads and directory listings are public to anyone who can reach this address; there is no login or encryption.",
        ])

    def _stop_share(self, _parameters):
        if self._share_server is None:
            return ExecutionResult(["Folder sharing is stopped."])
        self._share_server.shutdown()
        self._share_server.server_close()
        self._share_thread.join()
        self._share_server = None
        self._share_thread = None
        return ExecutionResult(["Folder sharing stopped."])
