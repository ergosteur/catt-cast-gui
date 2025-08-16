import sys
import shutil
import os
import subprocess
from typing import Optional
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QComboBox,
    QLineEdit,
    QPushButton,
    QLabel,
    QFileDialog,
    QSlider,
    QCheckBox,
    QStyle
)

from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal, QTimer

try:
    from catt_cast_gui.piped import get_best_piped_url, extract_video_id
    GET_PIPED_URL_AVAILABLE = True
except ImportError:
    GET_PIPED_URL_AVAILABLE = False
    # Define dummy functions so the rest of the code doesn't crash if the file is missing.
    def get_best_piped_url(*args, **kwargs):
        raise ImportError("could not import 'catt_cast_gui.piped' module. Piped URL functionality is disabled.")

    def extract_video_id(url: str) -> Optional[str]:
        # A simple fallback for the YouTube URL check.
        if "youtube.com" in url or "youtu.be" in url:
            return "dummy_id" # Return something non-None to trigger the check
        return None

class PipedWorker(QObject):
    """Worker to get a direct URL from a Piped instance."""
    url_found = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, video_url, piped_host):
        super().__init__()
        self.video_url = video_url
        self.piped_host = piped_host

    def run(self):
        """Fetch the URL."""
        try:
            if not self.piped_host.startswith(('http://', 'https://')):
                base_url = f"https://{self.piped_host}"
            else:
                base_url = self.piped_host

            print(f"CATT-Qt NG: Getting Piped URL for '{self.video_url}' via '{base_url}'")
            direct_url = get_best_piped_url(self.video_url, base_url, timeout=15)
            print(f"CATT-Qt NG: Found Piped URL -> {direct_url}")
            self.url_found.emit(direct_url)
        except Exception as e:
            print(f"CATT-Qt NG: Piped URL fetch failed -> {e}")
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class CattWorker(QObject):
    """Worker to run catt commands in a separate thread."""

    result = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()
    process_created = pyqtSignal(object)

    def __init__(self, command_args, is_local_cast=False, log_command=True):
        super().__init__()
        self.command_args = command_args
        self.is_local_cast = is_local_cast
        self.log_command = log_command

    def run(self):
        """Execute the catt command."""
        if self.is_local_cast:
            self._run_local_cast()
        else:
            self._run_blocking_command()

    def _run_local_cast(self):
        """Execute a local file cast command and fork to background."""
        try:
            cmd = ["catt"] + self.command_args
            if self.log_command:
                print(f"CATT-Qt NG: Running command -> {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # Create a new process group to be able to kill the process and its children
                start_new_session=True if sys.platform != "win32" else False,
            )
            self.process_created.emit(process)

            try:
                # Wait for a few seconds to see if it fails quickly
                return_code = process.wait(timeout=3)
                # If we get here, it exited before the timeout, which means failure.
                stderr = process.stderr.read()
                self.error.emit(stderr.strip() or f"catt command failed with exit code {return_code}")
            except subprocess.TimeoutExpired:
                # This is the success case: the process is still running.
                self.result.emit("Casting local file in background...")

        except FileNotFoundError:
            if self.log_command:
                print("CATT-Qt NG: Error -> 'catt' command not found.")
            self.error.emit("'catt' command not found. Is it installed and in your PATH?")
        except Exception as e:
            if self.log_command:
                print(f"CATT-Qt NG: An unexpected error occurred -> {e}")
            self.error.emit(f"An unexpected error occurred: {e}")
        finally:
            self.finished.emit()

    def _run_blocking_command(self):
        """Execute a standard blocking catt command."""
        try:
            # The first argument is always 'catt'
            cmd = ["catt"] + self.command_args
            if self.log_command:
                print(f"CATT-Qt NG: Running command -> {' '.join(cmd)}")
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,  # Raises CalledProcessError for non-zero exit codes
            )
            if self.log_command and process.stdout:
                print(f"CATT-Qt NG: stdout ->\n{process.stdout.strip()}")
            self.result.emit(process.stdout.strip())
        except FileNotFoundError:
            if self.log_command:
                print("CATT-Qt NG: Error -> 'catt' command not found.")
            self.error.emit("'catt' command not found. Is it installed and in your PATH?")
        except subprocess.CalledProcessError as e:
            if self.log_command:
                print(f"CATT-Qt NG: Command failed with exit code {e.returncode}")
                if e.stdout:
                    print(f"CATT-Qt NG: stdout (on error) ->\n{e.stdout.strip()}")
                if e.stderr:
                    print(f"CATT-Qt NG: stderr (on error) ->\n{e.stderr.strip()}")
            self.error.emit(e.stderr.strip() or f"catt command failed with exit code {e.returncode}")
        except Exception as e:
            if self.log_command:
                print(f"CATT-Qt NG: An unexpected error occurred -> {e}")
            self.error.emit(f"An unexpected error occurred: {e}")
        finally:
            self.finished.emit()


class CattQtNG(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CATT-Qt NG")
        self.setGeometry(100, 100, 550, 280)
        self.devices = []
        self.thread = None
        self.worker = None
        self.local_cast_process = None
        self.piped_worker_obj = None
        self._pending_piped_cast_info = None

        self.is_casting = False
        self.local_current_time = 0
        self.local_duration = 0

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(15000)  # Resync every 15 seconds
        self.status_timer.timeout.connect(self.request_status_update)

        # Timer for polling status immediately after casting to get faster feedback
        self.post_cast_poll_timer = QTimer(self)
        self.post_cast_poll_timer.setInterval(3000) # Poll every 3 seconds
        self.post_cast_poll_timer.timeout.connect(self._poll_status_after_cast)
        self.post_cast_poll_attempts = 0

        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(1000)  # Update local progress every second
        self.playback_timer.timeout.connect(self.update_local_progress)

        self.initUI()
        self.check_catt_availability()
        if not GET_PIPED_URL_AVAILABLE:
            self.piped_checkbox.setChecked(False)
            self.piped_checkbox.setEnabled(False)
            self.piped_host_input.setEnabled(False)
            self.piped_checkbox.setToolTip(
                "Feature disabled: piped_get_url.py not found in the same directory."
            )

    def closeEvent(self, event):
        """Ensure background processes are killed on exit."""
        self.kill_local_cast_process()
        event.accept()

    def kill_local_cast_process(self):
        """Kills the background catt process for local file casting, if it exists."""
        if not self.local_cast_process:
            return

        print("CATT-Qt NG: Stopping background local cast process.")
        # Kill the whole process group on POSIX to handle child processes
        if sys.platform != "win32":
            import signal
            try:
                os.killpg(os.getpgid(self.local_cast_process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass  # Process already gone
        else:
            self.local_cast_process.terminate()

        self.local_cast_process.wait(timeout=2)
        self.local_cast_process = None

    def initUI(self):
        central = QWidget()
        layout = QVBoxLayout()
        style = self.style()

        # Device selection
        device_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.refresh_button.setToolTip("Manually refresh the status of the selected device.")
        self.refresh_button.clicked.connect(self.on_refresh_clicked)
        self.rescan_button = QPushButton("Rescan")
        self.rescan_button.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.rescan_button.clicked.connect(self.scan_devices)
        device_layout.addWidget(QLabel("Device:"))
        device_layout.addWidget(self.device_combo, 1)
        device_layout.addWidget(self.refresh_button)
        device_layout.addWidget(self.rescan_button)
        layout.addLayout(device_layout)

        # URL/File input
        input_layout = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Enter URL or file path...")
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.browse_button.clicked.connect(self.browse_file)
        input_layout.addWidget(self.input_box)
        input_layout.addWidget(self.browse_button)
        layout.addLayout(input_layout)

        # Piped settings
        piped_layout = QHBoxLayout()
        self.piped_checkbox = QCheckBox("Use Piped for YouTube URLs")
        self.piped_host_input = QLineEdit()
        self.piped_host_input.setText("pipedapi.reallyaweso.me")
        piped_layout.addWidget(self.piped_checkbox)
        piped_layout.addWidget(self.piped_host_input, 1)
        layout.addLayout(piped_layout)

        # Controls
        control_layout = QHBoxLayout()
        self.cast_button = QPushButton("Cast")
        self.cast_button.clicked.connect(self.cast_media)
        self.cast_site_button = QPushButton("Cast as Site")
        self.cast_site_button.clicked.connect(self.cast_site)
        self.enqueue_button = QPushButton("Enqueue")
        self.enqueue_button.clicked.connect(self.enqueue_media)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setIcon(style.standardIcon(QStyle.SP_MediaStop))
        self.stop_button.clicked.connect(self.stop_media)
        control_layout.addStretch()
        control_layout.addWidget(self.cast_button)
        control_layout.addWidget(self.cast_site_button)
        control_layout.addWidget(self.enqueue_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # Status output
        self.status_label = QLabel("Welcome!")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Playback controls
        play_pause_layout = QHBoxLayout()
        self.rewind_button = QPushButton("-15s")
        self.rewind_button.setIcon(style.standardIcon(QStyle.SP_MediaSeekBackward))
        self.rewind_button.clicked.connect(self.rewind_media)
        self.play_pause_button = QPushButton("Play/Pause")
        self.play_pause_button.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        self.ffwd_button = QPushButton("+15s")
        self.ffwd_button.setIcon(style.standardIcon(QStyle.SP_MediaSeekForward))
        self.ffwd_button.clicked.connect(self.ffwd_media)
        self.skip_button = QPushButton("Skip")
        self.skip_button.setIcon(style.standardIcon(QStyle.SP_MediaSkipForward))
        self.skip_button.clicked.connect(self.skip_track)
        play_pause_layout.addStretch()
        play_pause_layout.addWidget(self.rewind_button)
        play_pause_layout.addWidget(self.play_pause_button)
        play_pause_layout.addWidget(self.ffwd_button)
        play_pause_layout.addWidget(self.skip_button)
        play_pause_layout.addStretch()
        layout.addLayout(play_pause_layout)

        # Playback progress
        progress_layout = QHBoxLayout()
        self.time_label = QLabel("00:00:00")
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.sliderReleased.connect(self.seek_media)
        self.duration_label = QLabel("00:00:00")
        progress_layout.addWidget(self.time_label)
        progress_layout.addWidget(self.progress_slider)
        progress_layout.addWidget(self.duration_label)
        layout.addLayout(progress_layout)

        # Volume control
        volume_layout = QHBoxLayout()
        self.mute_button = QPushButton("Mute")
        self.mute_button.setIcon(style.standardIcon(QStyle.SP_MediaVolume))
        self.mute_button.clicked.connect(self.toggle_mute)
        self.volume_down_button = QPushButton("-5%")
        self.volume_down_button.clicked.connect(self.volume_down)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.sliderReleased.connect(self.set_volume)
        self.volume_up_button = QPushButton("+5%")
        self.volume_up_button.clicked.connect(self.volume_up)
        volume_layout.addWidget(QLabel("Volume:"))
        volume_layout.addWidget(self.mute_button)
        volume_layout.addWidget(self.volume_down_button)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_up_button)
        layout.addLayout(volume_layout)

        self.reset_playback_ui()
        self.update_control_states()  # Set initial state of action buttons
        central.setLayout(layout)
        self.setCentralWidget(central)

    def check_catt_availability(self):
        if not shutil.which("catt"):
            self.status_label.setText(
                "Error: 'catt' not found. Please install it and ensure it's in your PATH."
            )
            self.set_controls_enabled(False)
        else:
            self.scan_devices()

    def set_playback_controls_enabled(self, enabled):
        """Enable or disable playback-specific controls."""
        self.progress_slider.setEnabled(enabled)
        self.volume_slider.setEnabled(enabled)
        self.rewind_button.setEnabled(enabled)
        self.play_pause_button.setEnabled(enabled)
        self.ffwd_button.setEnabled(enabled)
        self.skip_button.setEnabled(enabled)
        self.mute_button.setEnabled(enabled)
        self.volume_down_button.setEnabled(enabled)
        self.volume_up_button.setEnabled(enabled)

    def update_control_states(self):
        """Updates the enabled/disabled state of action buttons based on app state."""
        is_device_selected = self.get_selected_device_ip() is not None

        self.refresh_button.setEnabled(is_device_selected)
        self.cast_button.setEnabled(is_device_selected)
        self.cast_site_button.setEnabled(is_device_selected)
        self.stop_button.setEnabled(is_device_selected)

        self.enqueue_button.setEnabled(is_device_selected and self.is_casting)
        self.set_playback_controls_enabled(is_device_selected and self.is_casting)

    def set_controls_enabled(self, enabled):
        """Enable or disable all controls."""
        self.device_combo.setEnabled(enabled)
        self.rescan_button.setEnabled(enabled)
        self.input_box.setEnabled(enabled)
        self.browse_button.setEnabled(enabled)

        is_piped_available = GET_PIPED_URL_AVAILABLE
        self.piped_checkbox.setEnabled(enabled and is_piped_available)
        self.piped_host_input.setEnabled(enabled and is_piped_available)

        if enabled:
            # When re-enabling, restore the state of action buttons
            self.update_control_states()
        else:
            # When disabling, turn off all action buttons
            self.cast_button.setEnabled(False)
            self.cast_site_button.setEnabled(False)
            self.enqueue_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.refresh_button.setEnabled(False)
            self.set_playback_controls_enabled(False)

    def run_catt_command(self, command_args, on_result, on_error, disable_ui=True, is_local_cast=False, log_command=True):
        """Runs a catt command in a background thread."""
        if self.thread and self.thread.isRunning():
            if not disable_ui:  # This is a non-critical poll, just skip it
                return
            self.status_label.setText("An operation is already in progress.")
            return

        if disable_ui:
            self.set_controls_enabled(False)
        self.thread = QThread()
        self.worker = CattWorker(command_args, is_local_cast=is_local_cast, log_command=log_command)
        self.worker.moveToThread(self.thread)

        if is_local_cast:
            self.worker.process_created.connect(self.handle_process_created)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._on_thread_finished)
        if disable_ui:
            self.worker.finished.connect(lambda: self.set_controls_enabled(True))

        self.worker.result.connect(on_result)
        self.worker.error.connect(on_error)

        self.thread.start()

    def _on_thread_finished(self):
        """Clear references to the finished thread and worker."""
        self.thread = None
        self.worker = None

    def _get_url_from_piped_and_run(self, video_url, piped_host, device_ip, cast_mode):
        if self.thread and self.thread.isRunning():
            self.status_label.setText("An operation is already in progress.")
            return

        # Store the info needed for the next step after the Piped URL is fetched.
        self._pending_piped_cast_info = {
            "device_ip": device_ip,
            "cast_mode": cast_mode,
            "url": None,  # This will be filled in by the worker
        }

        self.set_controls_enabled(False)
        self.thread = QThread()
        self.piped_worker_obj = PipedWorker(video_url, piped_host)
        self.piped_worker_obj.moveToThread(self.thread)

        # The worker will store the URL in our pending info dict.
        # The actual casting will be triggered after this thread finishes.
        def on_url_found(url):
            if self._pending_piped_cast_info:
                self._pending_piped_cast_info["url"] = url

        self.thread.started.connect(self.piped_worker_obj.run)
        self.piped_worker_obj.url_found.connect(on_url_found)
        self.piped_worker_obj.error.connect(self.handle_piped_error)
        self.piped_worker_obj.finished.connect(self.thread.quit)
        self.piped_worker_obj.finished.connect(self.piped_worker_obj.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._on_piped_thread_finished)

        self.thread.start()

    def _on_piped_thread_finished(self):
        self.thread = None
        self.piped_worker_obj = None

        if not self._pending_piped_cast_info:
            return

        cast_info = self._pending_piped_cast_info
        self._pending_piped_cast_info = None  # Clear it to prevent re-entry

        # If the worker finished but didn't find a URL, the error handler
        # should have already re-enabled the UI.
        if not cast_info.get("url"):
            return

        # Now that the Piped worker thread is finished, start the CATT worker thread.
        url, device_ip, cast_mode = cast_info["url"], cast_info["device_ip"], cast_info["cast_mode"]
        device_name = self.device_combo.currentText()

        if cast_mode == 'cast':
            self.kill_local_cast_process()
            self.status_label.setText(f"Casting to {device_name}...")
            self.run_catt_command(
                command_args=["-d", device_ip, "cast", url],
                on_result=self.handle_cast_success,
                on_error=self.handle_command_error,
                is_local_cast=False,
                disable_ui=True,
            )
        elif cast_mode == 'add':
            self.status_label.setText(f"Enqueuing on {device_name}...")
            self.run_catt_command(
                command_args=["-d", device_ip, "add", url],
                on_result=lambda res: self.status_label.setText(f"{device_name.split(' (')[0]}: {res.strip()}"),
                on_error=self.handle_command_error,
                disable_ui=True,
            )

    def handle_process_created(self, process):
        """Store the handle to the background process."""
        self.local_cast_process = process

    def on_device_changed(self):
        """Handle when the selected device is changed."""
        self.post_cast_poll_timer.stop()
        self.status_timer.stop()
        self.playback_timer.stop()
        self.is_casting = False
        self.reset_playback_ui()
        self.update_control_states()

        ip = self.get_selected_device_ip()
        if ip:
            # A valid device is selected, check its status.
            self.status_label.setText("Checking device status...")
            self.request_status_update()
        else:
            self.status_label.setText("Please select a device.")

    def scan_devices(self):
        self.status_label.setText("Scanning for devices...")
        self.run_catt_command(
            command_args=["scan"],
            on_result=self.handle_scan_result,
            on_error=self.handle_command_error,
        )

    def handle_scan_result(self, output):
        self.device_combo.blockSignals(True)
        self.devices = []
        self.device_combo.clear()
        self.device_combo.addItem("Select a device...", None)

        for line in output.splitlines():
            if line:
                # Format: "IP - Name - Model"
                parts = line.split(" - ")
                if len(parts) >= 2:
                    ip = parts[0].strip()
                    name = parts[1].strip()
                    self.devices.append((name, ip))
                    self.device_combo.addItem(f"{name} ({ip})", ip)
        self.device_combo.blockSignals(False)

        if not self.devices:
            self.status_label.setText("No devices found.")
        else:
            self.status_label.setText(f"Found {len(self.devices)} device(s).")

        # Trigger a device change to set the initial UI state correctly
        # (which will be the "no device selected" state).
        self.on_device_changed()

    def handle_command_error(self, error_message):
        self.status_label.setText(f"Error: {error_message}")

    def get_selected_device_ip(self):
        if self.device_combo.count() == 0:
            self.status_label.setText("No devices found. Please scan.")
            return None

        idx = self.device_combo.currentIndex()
        if idx < 0 or not self.devices:
            self.status_label.setText("No device selected.")
            return None
        return self.device_combo.itemData(idx)

    def cast_media(self):
        ip = self.get_selected_device_ip()
        if not ip:
            return

        media = self.input_box.text().strip()
        if not media:
            self.status_label.setText("Enter a URL or file path.")
            return

        is_youtube_url = extract_video_id(media) is not None
        if self.piped_checkbox.isChecked() and is_youtube_url:
            piped_host = self.piped_host_input.text().strip()
            if not piped_host:
                self.status_label.setText("Piped API Hostname is required.")
                return
            self.status_label.setText("Getting direct URL from Piped...")
            self._get_url_from_piped_and_run(media, piped_host, ip, 'cast')
            return

        is_local_file = os.path.exists(media)


        if is_local_file:
            self.kill_local_cast_process()

        device_name = self.device_combo.currentText()
        self.status_label.setText(f"Casting to {device_name}...")
        self.run_catt_command(
            command_args=["-d", ip, "cast", media],
            on_result=self.handle_cast_success,
            on_error=self.handle_command_error,
            is_local_cast=is_local_file,
        )

    def handle_piped_error(self, error_message):
        self.status_label.setText(f"Piped Error: {error_message}")
        self._pending_piped_cast_info = None  # Clear pending operation on error
        self.set_controls_enabled(True)

    def cast_site(self):
        ip = self.get_selected_device_ip()
        if not ip:
            return

        url = self.input_box.text().strip()
        if not url:
            self.status_label.setText("Enter a URL to cast as a site.")
            return

        device_name = self.device_combo.currentText()
        self.status_label.setText(f"Casting site to {device_name}...")
        self.run_catt_command(
            command_args=["-d", ip, "cast_site", url],
            on_result=lambda res: self.status_label.setText(f"Successfully cast site to {device_name}."),
            on_error=self.handle_command_error,
        )

    def stop_media(self):
        self.kill_local_cast_process()

        ip = self.get_selected_device_ip()
        if not ip:
            return

        self.post_cast_poll_timer.stop()
        self.status_timer.stop()
        self.playback_timer.stop()
        self.is_casting = False
        self.reset_playback_ui()

        device_name = self.device_combo.currentText()
        self.status_label.setText(f"Stopping playback on {device_name}...")
        self.run_catt_command(
            command_args=["-d", ip, "stop"],
            on_result=lambda res: self.status_label.setText(
                f"Playback stopped on {device_name}."
            ),
            on_error=self.handle_command_error,
        )

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Media File")
        if path:
            self.input_box.setText(path)

    def handle_cast_success(self, result):
        """Called when the 'catt cast' command finishes successfully."""
        self._start_fast_poll(message=f"Cast sent to {self.device_combo.currentText()}. Confirming playback...")

    def _start_fast_poll(self, message="Confirming action..."):
        """Stops regular timers and starts a rapid poll to get quick feedback."""
        self.status_label.setText(message)
        self.status_timer.stop()
        self.playback_timer.stop()
        self.post_cast_poll_attempts = 0
        self.post_cast_poll_timer.start()
        self._poll_status_after_cast()  # Fire one off immediately without waiting 2s

    def _poll_status_after_cast(self):
        """Requests status update shortly after casting to get timely feedback."""
        self.post_cast_poll_attempts += 1
        print(f"CATT-Qt NG: Fast-polling for status, attempt {self.post_cast_poll_attempts}...")

        if self.post_cast_poll_attempts > 5:  # Give up after 5 attempts (10 seconds)
            print("CATT-Qt NG: Fast-poll timed out. Could not confirm action.")
            self.post_cast_poll_timer.stop()
            self._set_idle_state(message="Action sent, but status is unknown.")
            return
        self.request_status_update()

    def reset_playback_ui(self):
        self.set_playback_controls_enabled(False)
        self.play_pause_button.setText("Play/Pause")
        self.time_label.setText("00:00:00")
        self.play_pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.local_current_time = 0
        self.duration_label.setText("00:00:00")
        self.progress_slider.blockSignals(True)
        self.progress_slider.setValue(0)
        self.progress_slider.setMaximum(1)
        self.progress_slider.blockSignals(False)
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(0)
        self.volume_slider.blockSignals(False)

    def _set_idle_state(self, message="Idle. Ready to cast."):
        """Sets the UI to a clean, idle state, stopping any active timers."""
        # Avoid redundant UI updates if we are already idle.
        if not self.is_casting and self.status_label.text() == message:
            return

        print(f"CATT-Qt NG: Setting idle state. Message: '{message}'")
        self.is_casting = False
        self.status_timer.stop()
        self.playback_timer.stop()
        self.reset_playback_ui()
        self.status_label.setText(message)
        self.update_control_states()

    def request_status_update(self):
        ip = self.get_selected_device_ip()
        if not ip:
            return

        self.run_catt_command(
            command_args=["-d", ip, "status"],
            on_result=self.handle_status_update,
            on_error=self.handle_status_error,
            disable_ui=False,
            log_command=False,
        )

    def update_local_progress(self):
        """Update UI based on local timer, not a catt call."""
        if not self.is_casting:
            self.playback_timer.stop()
            return

        self.local_current_time += 1
        self.time_label.setText(self.format_time(self.local_current_time))
        self.progress_slider.blockSignals(True)
        self.progress_slider.setValue(self.local_current_time)
        self.progress_slider.blockSignals(False)

        if self.local_duration > 0 and self.local_current_time >= self.local_duration:
            self.playback_timer.stop()

    def handle_status_update(self, output):
        # This is the "resync" point. It updates the UI from catt's state
        # and starts/stops the local timers.
        was_casting = self.is_casting  # Capture state before update
        status_data = {}
        for line in output.strip().splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                status_data[key.strip().lower()] = value.strip()

        # If there's no title, we assume it's idle or just showing volume.
        # This happens when the device is on the backdrop or ambient screen.
        if "title" not in status_data:
            # If we are polling after a cast, we don't change the UI, just let the timer try again.
            if self.post_cast_poll_timer.isActive():
                return

            if 'volume' in status_data:
                self._set_idle_state()
                # Even when idle, we can get volume info.
                volume = int(status_data.get("volume", 0))
                self.volume_slider.blockSignals(True)
                self.volume_slider.setValue(volume)
                self.volume_slider.blockSignals(False)
            else:
                self._set_idle_state(message="Device is idle or not responding.")
            return

        # If we got here, something is playing. Ensure our state reflects that.
        # This is the success case for our post-cast poll.
        if self.post_cast_poll_timer.isActive():
            self.post_cast_poll_timer.stop()
            print("CATT-Qt NG: Fast-poll successful. State confirmed.")

        if not self.is_casting:
            self.is_casting = True
            self.update_control_states()
            self.status_timer.start()  # Start the regular 15s timer

        style = self.style()
        player_state = status_data.get("state", "UNKNOWN").capitalize()
        title = status_data.get("title", "No title")
        self.status_label.setText(f"{player_state}: {title}")

        if player_state == "Playing":
            self.play_pause_button.setText("Pause")
            self.play_pause_button.setIcon(style.standardIcon(QStyle.SP_MediaPause))
            self.playback_timer.start()
        elif player_state == "Paused":
            self.play_pause_button.setText("Play")
            self.play_pause_button.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
            self.playback_timer.stop()
        else:
            self.play_pause_button.setText("Play/Pause")
            self.playback_timer.stop()

        # Volume
        volume = int(status_data.get("volume", 0))
        is_muted = status_data.get("volume muted", "False").lower() == "true"
        if is_muted:
            self.mute_button.setIcon(style.standardIcon(QStyle.SP_MediaVolumeMuted))
        else:
            self.mute_button.setIcon(style.standardIcon(QStyle.SP_MediaVolume))
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(volume)
        self.volume_slider.blockSignals(False)

        # Progress
        current_time = None
        duration = None
        if "time" in status_data:
            try:
                time_parts = status_data["time"].split(" / ")
                time_str = time_parts[0]  # e.g., "0:01:23"
                h, m, s = map(int, time_str.split(":"))
                current_time = h * 3600 + m * 60 + s

                if len(time_parts) > 1:
                    duration_str = time_parts[1].split(" ")[0]  # e.g., "1:23:45"
                    h, m, s = map(int, duration_str.split(":"))
                    duration = h * 3600 + m * 60 + s
            except (ValueError, IndexError):
                # Handles cases where time is "N/A" or malformed
                pass

        is_stream = not duration or duration <= 0

        if is_stream:
            self.local_duration = 0
            if not was_casting:  # First update for this media
                self.local_current_time = 0
            self.progress_slider.setEnabled(False)
            self.duration_label.setText("Stream")
        else:  # Not a stream, has a valid duration
            self.local_duration = duration
            self.local_current_time = current_time if current_time is not None else 0
            self.progress_slider.setEnabled(True)
            self.progress_slider.blockSignals(True)
            self.progress_slider.setMaximum(int(self.local_duration))
            self.progress_slider.setValue(int(self.local_current_time))
            self.progress_slider.blockSignals(False)
            self.duration_label.setText(self.format_time(self.local_duration))

        self.time_label.setText(self.format_time(self.local_current_time))

    def on_refresh_clicked(self):
        """Manually trigger a status update for the selected device."""
        ip = self.get_selected_device_ip()
        if not ip:
            return
        self._start_fast_poll(message="Refreshing status...")

    def handle_status_error(self, error_message):
        # "Nothing is currently playing" is another key phrase for an idle device.
        if "inactive" in error_message or "Nothing is currently playing" in error_message:
            self._set_idle_state()

    def format_time(self, seconds):
        if seconds is None or seconds < 0:
            return "00:00:00"
        s = int(seconds)
        h, m, s = s // 3600, (s % 3600) // 60, s % 60
        return f"{h:02}:{m:02}:{s:02}"

    def set_volume(self):
        ip = self.get_selected_device_ip()
        if not ip:
            return
        level = self.volume_slider.value()
        self.run_catt_command(
            ["-d", ip, "volume", str(level)],
            on_result=lambda r: self.request_status_update(),
            on_error=self.handle_command_error,
            disable_ui=False,
        )

    def seek_media(self):
        ip = self.get_selected_device_ip()
        if not ip:
            return
        position = self.progress_slider.value()
        self.local_current_time = position  # Immediately update local time for responsiveness
        self.time_label.setText(self.format_time(self.local_current_time))
        self.run_catt_command(
            ["-d", ip, "seek", str(position)],
            on_result=lambda r: self.request_status_update(),
            on_error=self.handle_command_error,
            disable_ui=False,
        )

    def enqueue_media(self):
        ip = self.get_selected_device_ip()
        if not ip:
            return

        media = self.input_box.text().strip()
        if not media:
            self.status_label.setText("Enter a URL to enqueue.")
            return

        is_youtube_url = extract_video_id(media) is not None
        if self.piped_checkbox.isChecked() and is_youtube_url:
            piped_host = self.piped_host_input.text().strip()
            if not piped_host:
                self.status_label.setText("Piped API Hostname is required.")
                return
            self.status_label.setText("Getting direct URL from Piped...")
            self._get_url_from_piped_and_run(media, piped_host, ip, 'add')
            return

        device_name = self.device_combo.currentText()
        self.status_label.setText(f"Enqueuing on {device_name}...")
        self.run_catt_command(
            ["-d", ip, "add", media],
            on_result=lambda res: self.status_label.setText(f"{device_name.split(' (')[0]}: {res.strip()}"),
            on_error=self.handle_command_error,
        )

    def _run_quick_action_command(self, action_args):
        """Runs a short command (like play/pause) and triggers a fast poll on success."""
        ip = self.get_selected_device_ip()
        if not ip:
            return

        # These are quick actions, so we don't disable the whole UI.
        # The check in run_catt_command prevents spamming.
        self.run_catt_command(
            ["-d", ip] + action_args,
            on_result=lambda r: self._start_fast_poll(),
            on_error=self.handle_command_error,
            disable_ui=False,
        )

    def toggle_play_pause(self):
        self._run_quick_action_command(["play_toggle"])

    def rewind_media(self):
        self._run_quick_action_command(["rewind", "15"])

    def ffwd_media(self):
        self._run_quick_action_command(["ffwd", "15"])

    def skip_track(self):
        self._run_quick_action_command(["skip"])

    def toggle_mute(self):
        self._run_quick_action_command(["volumemute"])

    def volume_down(self):
        self._run_quick_action_command(["volumedown", "5"])

    def volume_up(self):
        self._run_quick_action_command(["volumeup", "5"])


def main():
    app = QApplication(sys.argv)
    window = CattQtNG()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
