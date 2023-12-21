import logging
import os.path
import pathlib
import re
import time
from threading import Thread

from PyQt5.QtWidgets import QComboBox, QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt
import sys
from github import Github, GitRelease
from crumbs import Parameters
from urllib import request
from packaging import version

logging.basicConfig()
logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    releases = {}
    github_client: Github
    current_index = None
    config = None
    last_selected_release_path = None
    details_box: QLabel

    def __init__(self, title: str, config_parameters: Parameters):
        super().__init__()
        self.config = config_parameters

        self.github_client = Github(self.config["github-token"])

        if not os.path.exists(self.config["release-dir"]):
            os.mkdir(self.config["release-dir"])

        self.setWindowTitle(title)

        # get the last launched release version
        self.last_selected_release_path = os.path.realpath(os.path.join(self.config["release-dir"], "last-selected-release"))
        if os.path.exists(self.last_selected_release_path):
            with open(self.last_selected_release_path, "r") as last:
                self.current_index = last.read()


        if self.current_index is None:
            self.current_index = list(self.get_releases().keys())[0]

        # build release dropdown
        release_combobox = QComboBox()
        index = 0
        releases = self.filter_releases(self.get_releases())
        logger.debug("Filtered releases %s" % releases)
        for title, release in releases.items():
            release_combobox.addItem(title, release.id)

            if title == self.current_index:
                release_combobox.setCurrentIndex(index)

            index += 1

        release_combobox.currentTextChanged.connect(self.select_release)

        launch_button = QPushButton("Launch")
        self.status_box = QLabel("")
        self.update_status("Loading...")
        launch_button.clicked.connect(self.launch_release)

        self.details_box = QLabel("")
        self.details_box.setOpenExternalLinks(True)
        self.details_box.setTextFormat(Qt.RichText)
        self.details_box.setTextInteractionFlags(Qt.LinksAccessibleByMouse)

        control_layout = QVBoxLayout()
        layout = QHBoxLayout()
        control_layout.addWidget(release_combobox)
        control_layout.addWidget(launch_button)
        control_layout.addWidget(self.status_box)

        layout.addLayout(control_layout)
        layout.addWidget(QLabel(""))
        layout.addWidget(self.details_box)

        container = QWidget()
        container.setLayout(layout)

        self.setCentralWidget(container)
        self.select_release(self.current_index)
        self.clear_status()

    def get_releases(self):
        if len(self.releases.keys()) == 0:
            self.releases = {r.title.strip().lower().replace("ultimaker cura", "").strip(): r for r in self.github_client.get_repo("Ultimaker/Cura").get_releases()}

            logger.debug("Found %d releases\n%s" % (len(self.releases.keys()), [r for r in self.releases.keys()]))
        return self.releases

    def select_release(self, index):
        self.current_index = index

        release = self.get_releases()[self.current_index]
        self.update_details(release)

    def filter_releases(self, releases):
        filter_pattern = re.compile(r"^v?[\d\.]+(\-[a-z]+)?$", re.IGNORECASE)
        sub_pattern = re.compile(r"^v", re.IGNORECASE)
        return {re.sub(sub_pattern, "", t): r for t, r in releases.items() if re.search(filter_pattern, t)}

    def filter_assets(self, assets, key: callable = lambda a: a.name):
        logger.debug("Filtering %d assets\n%s" % (len(assets), [a.name for a in assets]))
        pattern = None
        if self.config["os-type"] == "linux":
            pattern = r'(\-linux)?\.AppImage$'
        if self.config["os-type"] == "mac":
            pattern = r'\-Darwin\.dmg$'
        if self.config["os-type"] == "windows":
            pattern = r'\-amd64.exe$'

        filtered_assets = []
        for asset in assets:
            if re.search(pattern, key(asset), re.IGNORECASE):
                filtered_assets.append(asset)
        return filtered_assets

    def download_asset(self, asset, file_path: pathlib.Path, launch: bool = False):
        self.update_status("Downloading...")
        logger.debug("Downloading %s to %s" % (asset.browser_download_url, file_path))

        with request.urlopen(asset.browser_download_url) as downloaded_file:
            with open(file_path, "wb") as local_file:
                local_file.write(downloaded_file.read())

        os.chmod(file_path, 0o744)

        if launch:
            self.launch_file(file_path)

    def launch_file(self, file_path: pathlib.Path):
        logger.debug("Launching %s" % file_path)
        self.update_status("Launching...")

        thread = Thread(target=os.system, args=["GDK_BACKEND=x11 %s" % file_path])
        thread.start()

        thread = Thread(target=self.clear_status, args=[10])
        thread.start()

    def launch_release(self):
        release = self.get_releases()[self.current_index]
        assets = self.filter_assets([a for a in release.get_assets()])
        assert len(assets) > 0

        asset = next(iter(assets))

        file_path = os.path.realpath(os.path.join(self.config["release-dir"], asset.name))
        if os.path.exists(file_path) and os.path.getsize(file_path) == 0:
            os.unlink(file_path)

        if not os.path.exists(file_path):
            thread = Thread(target=self.download_asset, args=[asset, file_path, True])
            thread.start()
        else:
            self.launch_file(file_path)

        with open(self.last_selected_release_path, "w") as last:
            last.write(self.current_index)

    def update_details(self, release: GitRelease):
        assets_list = "<br />   ".join([a.name for a in release.get_assets()])
        truncated_body = release.body[0:100].replace("\r", "<br />")
        text = f"""
{release.title}<br /><br />

{truncated_body}<br /><br />

Assets:<br />
  {assets_list}
<br /><br />
<a href=\"{release.html_url}\">more..</a>
"""

        self.details_box.setText(text)

    def update_status(self, status: str):
        logger.debug("Setting status to %s" % status)
        self.status_box.setText(status)
        self.status_box.repaint()

    def clear_status(self, delay: int = 0):
        time.sleep(delay)
        self.update_status("")

if __name__ == '__main__':
    app = QApplication(sys.argv)

    parameters = Parameters()
    parameters.add_parameter(options=["--release-dir"], default=".cura_launcher")
    parameters.add_parameter(options=["--github-token"], required=True)
    parameters.add_parameter(options=["--log-level"], default="INFO", only=list(logging._nameToLevel.keys()))
    parameters.add_parameter(options=["--os-type"], default="linux", only=["linux", "mac", "windows"])
    parameters.parse()

    logger.setLevel(parameters["log_level"].upper())
    logger.debug(f"{parameters=}")

    if parameters["github-token"] is None:
        logger.error("--github-token is required")
        sys.exit(1)

    w = MainWindow("Ultimaker Cura Launcher", parameters)
    w.show()
    app.exec_()
