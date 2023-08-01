import os
import sys
import subprocess
import configparser
import json
import shutil
import zipfile
import psutil
import requests
import time
import threading
from bs4 import BeautifulSoup
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QMessageBox, QHBoxLayout, QProgressBar, QSizePolicy, QFileDialog
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QIcon, QPixmap
import webbrowser
import qdarktheme

CONFIG_FILE_PATH = "config.ini"
global stopped, steampid
steampid = None
stopped = False

def cwd():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def check_steamcmd():
    steamcmd_path = get_steamcmd_path()
    steamcmd_exe_path = os.path.join(steamcmd_path, "steamcmd.exe")

    if not os.path.exists(steamcmd_exe_path):
        return False

    return True

def valid_id(workshop_id):
    url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
    response = requests.get(url)
    response.raise_for_status()
    content = response.text
    soup = BeautifulSoup(content, "html.parser")

    try:
        soup.find("div", class_="rightDetailsBlock").text.strip()
        soup.find("div", class_="workshopItemTitle").text.strip()
        soup.find("div", class_="detailsStatRight").text.strip()
        stars_div = soup.find("div", class_="fileRatingDetails")
        stars_div.find("img")["src"]
        return True
    except:
        return False

def convert_speed(speed_bytes):
    if speed_bytes < 1024:
        return speed_bytes, "B/s"
    elif speed_bytes < 1024 * 1024:
        return speed_bytes / 1024, "KB/s"
    elif speed_bytes < 1024 * 1024 * 1024:
        return speed_bytes / (1024 * 1024), "MB/s"
    else:
        return speed_bytes / (1024 * 1024 * 1024), "GB/s"

def create_default_config():
    config = configparser.ConfigParser()
    config["Settings"] = {
        "SteamCMDPath": cwd(),
        "DestinationFolder": ""
    }
    with open(CONFIG_FILE_PATH, "w") as config_file:
        config.write(config_file)

def run_steamcmd_command(command):
    steamcmd_path = get_steamcmd_path()

    process = subprocess.Popen(
        [steamcmd_path + "\steamcmd.exe"] + command.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    global steampid
    steampid = process.pid

    if process.poll() is not None:
        return process.returncode

    process.communicate()

    if process.returncode != 0:
        show_message("Warning", "SteamCMD encountered an error while downloading, try again!")

    return process.returncode

def get_steamcmd_path():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE_PATH)
    return config.get("Settings", "SteamCMDPath", fallback=cwd())

def extract_json_data(json_path):
    with open(json_path, "r") as json_file:
        data = json.load(json_file)
    return data["Type"], data["FolderName"]

def convert_bytes_to_readable(size_in_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0

def get_workshop_file_size(workshop_id, raw=None):
    url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}&searchtext="
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    file_size_element = soup.find("div", class_="detailsStatRight")

    try:
        if raw:
            file_size_text = file_size_element.get_text(strip=True)
            file_size_text = file_size_text.replace(",", "")
            file_size_in_mb = float(file_size_text.replace(" MB", ""))
            file_size_in_bytes = int(file_size_in_mb * 1024 * 1024)
            return convert_bytes_to_readable(file_size_in_bytes)

        if file_size_element:
            file_size_text = file_size_element.get_text(strip=True)
            file_size_text = file_size_text.replace(",", "")
            file_size_in_mb = float(file_size_text.replace(" MB", ""))
            file_size_in_bytes = int(file_size_in_mb * 1024 * 1024)
            return file_size_in_bytes
        return None
    except:
        return None

def update_progress_bar(current_size, file_size, progress_bar):
    if file_size is not None:
        progress = int(current_size / file_size * 100)
        progress_bar.setValue(progress)

def check_and_update_progress(file_size, folder_name_path, progress_bar, speed_label):
    previous_net_speed = 0

    while not stopped:
        current_size = sum(os.path.getsize(os.path.join(folder_name_path, f)) for f in os.listdir(folder_name_path))
        update_progress_bar(current_size, file_size, progress_bar)

        current_net_speed = psutil.net_io_counters().bytes_recv

        net_speed_bytes = current_net_speed - previous_net_speed
        previous_net_speed = current_net_speed

        net_speed, speed_unit = convert_speed(net_speed_bytes)

        speed_label.setText(f"Network Speed: {net_speed:.2f} {speed_unit}")

        QCoreApplication.processEvents()
        time.sleep(1)

def download_workshop_map(workshop_id, destination_folder, progress_bar, speed_label):
    file_size = get_workshop_file_size(workshop_id)
    if file_size is None:
        show_message("Error", "Failed to retrieve file size.")
        return

    download_folder = os.path.join(get_steamcmd_path(), "steamapps", "workshop", "downloads", "311210", workshop_id)
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)

    command = f"+login anonymous +workshop_download_item 311210 {workshop_id} +quit"
    progress_thread = threading.Thread(target=check_and_update_progress, args=(file_size, download_folder, progress_bar, speed_label))
    progress_thread.daemon = True
    progress_thread.start()

    run_steamcmd_command(command)

    global stopped
    stopped = True
    progress_bar.setValue(100)

    map_folder = os.path.join(get_steamcmd_path(), "steamapps", "workshop", "content", "311210", workshop_id)

    json_file_path = os.path.join(map_folder, "workshop.json")

    if os.path.exists(json_file_path):
        global mod_type
        mod_type, folder_name = extract_json_data(json_file_path)

        if mod_type == "mod":
            mods_folder = os.path.join(destination_folder, "mods")
            folder_name_path = os.path.join(mods_folder, folder_name, "zone")
        elif mod_type == "map":
            usermaps_folder = os.path.join(destination_folder, "usermaps")
            folder_name_path = os.path.join(usermaps_folder, folder_name, "zone")
        else:
            show_message("Error", "Invalid map type in workshop.json.")
            return

        os.makedirs(folder_name_path, exist_ok=True)

        try:
            shutil.copytree(map_folder, folder_name_path, dirs_exist_ok=True)
        except Exception as E:
            print(f"Error copying files: {E}")

        show_message("Download Complete", f"{mod_type} files are downloaded at \n{folder_name_path}\nYou can run the game now!", icon=QMessageBox.Information)

def show_message(title, message, icon=QMessageBox.Warning):
    msg = QMessageBox()
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setIcon(icon)
    msg.exec_()

class DownloadThread(QThread):
    finished = pyqtSignal()

    def __init__(self, workshop_id, destination_folder, progress_bar, label_speed):
        super().__init__()
        self.workshop_id = workshop_id
        self.destination_folder = destination_folder
        self.progress_bar = progress_bar
        self.label_speed = label_speed

    def run(self):
        download_workshop_map(self.workshop_id, self.destination_folder, self.progress_bar, self.label_speed)
        self.finished.emit()

class WorkshopDownloaderApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

        if not check_steamcmd():
            self.show_warning_message()

        self.download_thread = None
        self.button_download.setEnabled(True)
        self.button_stop.setEnabled(False)

    def show_warning_message(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Warning")
        msg_box.setWindowIcon(QIcon('ryuk.ico'))
        msg_box.setText("steamcmd.exe was not found in the specified directory.\nPress Download to get it or Press OK and select it from there!.")
        msg_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)

        download_button = msg_box.addButton("Download", QMessageBox.AcceptRole)
        download_button.clicked.connect(self.download_steamcmd)

        result = msg_box.exec_()
        if result == QMessageBox.Cancel:
            sys.exit(0)

    def download_steamcmd(self):
        steamcmd_url = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
        steamcmd_zip_path = os.path.join(cwd(), "steamcmd.zip")

        try:
            response = requests.get(steamcmd_url)
            response.raise_for_status()

            with open(steamcmd_zip_path, "wb") as zip_file:
                zip_file.write(response.content)

            with zipfile.ZipFile(steamcmd_zip_path, "r") as zip_ref:
                zip_ref.extractall(cwd())

            if check_steamcmd():
                show_message("Success", "SteamCMD has been downloaded and extracted.", icon=QMessageBox.Information)
                os.remove(steamcmd_zip_path)
            else:
                show_message("Error", "Failed to find steamcmd.exe after extraction.")
                os.remove(steamcmd_zip_path)
        except requests.exceptions.RequestException as e:
            show_message("Error", f"Failed to download SteamCMD: {e}")
            os.remove(steamcmd_zip_path)
        except zipfile.BadZipFile:
            show_message("Error", "Failed to extract SteamCMD. The downloaded file might be corrupted.")
            os.remove(steamcmd_zip_path)

    def initUI(self):
        self.setWindowTitle('BOIII Workshop Downloader v0.1.2-beta')
        self.setWindowIcon(QIcon('ryuk.ico'))
        self.setGeometry(100, 100, 400, 200)

        layout = QVBoxLayout()

        browse_layout = QHBoxLayout()

        self.label_workshop_id = QLabel("Enter the Workshop ID of the map/mod you want to download:")
        browse_layout.addWidget(self.label_workshop_id, 3)

        self.button_browse = QPushButton("Browse")
        self.button_browse.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.button_browse.clicked.connect(self.open_browser)
        browse_layout.addWidget(self.button_browse, 1)

        layout.addLayout(browse_layout)

        info_workshop_layout = QHBoxLayout()

        self.edit_workshop_id = QLineEdit()
        self.edit_workshop_id.setPlaceholderText("Workshop ID => Press info to see map/mod info")
        info_workshop_layout.addWidget(self.edit_workshop_id, 3)

        layout.addLayout(info_workshop_layout)
        self.info_button = QPushButton("Info")
        self.info_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.info_button.clicked.connect(self.show_map_info)
        info_workshop_layout.addWidget(self.info_button, 1)

        self.label_destination_folder = QLabel("Enter Your BOIII folder:")
        layout.addWidget(self.label_destination_folder, 3)

        Boiii_Input = QHBoxLayout()
        self.edit_destination_folder = QLineEdit()
        self.edit_destination_folder.setPlaceholderText("Your BOIII Instalation folder")
        Boiii_Input.addWidget(self.edit_destination_folder, 90)

        layout.addLayout(Boiii_Input)

        self.button_BOIII_browse = QPushButton("Select")
        self.button_BOIII_browse.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.button_BOIII_browse.clicked.connect(self.open_BOIII_browser)
        Boiii_Input.addWidget(self.button_BOIII_browse, 10)

        self.label_steamcmd_path = QLabel("Enter SteamCMD path (default):")
        layout.addWidget(self.label_steamcmd_path)

        steamcmd_path = QHBoxLayout()
        self.edit_steamcmd_path = QLineEdit()
        steamcmd_path.addWidget(self.edit_steamcmd_path, 90)

        self.button_steamcmd_browse = QPushButton("Select")
        self.button_steamcmd_browse.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.button_steamcmd_browse.clicked.connect(self.open_steamcmd_path_browser)
        steamcmd_path.addWidget(self.button_steamcmd_browse, 10)

        layout.addLayout(steamcmd_path)
        layout.addSpacing(10)

        buttons_layout = QHBoxLayout()

        self.button_download = QPushButton("Download")
        self.button_download.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.button_download.clicked.connect(self.download_map)
        buttons_layout.addWidget(self.button_download, 75)

        self.button_stop = QPushButton("Stop")
        self.button_stop.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.button_stop.clicked.connect(self.stop_download)
        buttons_layout.addWidget(self.button_stop, 25)

        layout.addLayout(buttons_layout)

        InfoBar = QHBoxLayout()

        self.label_speed = QLabel("Network Speed: 0 KB/s")
        InfoBar.addWidget(self.label_speed, 3)

        self.label_file_size = QLabel("File size: 0KB")
        InfoBar.addWidget(self.label_file_size, 1)

        InfoWidget = QWidget()
        InfoWidget.setLayout(InfoBar)

        layout.addWidget(InfoWidget)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar, 75)

        self.setLayout(layout)

        self.load_config()

    def download_map(self):
        global stopped
        stopped = False

        if not check_steamcmd():
            self.show_warning_message()
            return

        workshop_id = self.edit_workshop_id.text()
        if not workshop_id.isdigit():
            QMessageBox.warning(self, "Warning", "Please enter a valid Workshop ID.")
            return

        if not valid_id(workshop_id):
            QMessageBox.warning(self, "Warning", "Please enter a valid Workshop ID.")
            return

        steamcmd_path = get_steamcmd_path()
        steamcmd_exe_path = os.path.join(steamcmd_path, "steamcmd.exe")
        steamcmd_size = os.path.getsize(steamcmd_exe_path)
        if steamcmd_size < 3 * 1024 * 1024:
            show_message("Warning", "Please wait a bit until SteamCMD downloads and initializes. It might take some time, but it will only happen once.", icon=QMessageBox.Warning)

        destination_folder = self.edit_destination_folder.text()
        steamcmd_path = self.edit_steamcmd_path.text()
        self.label_file_size.setText(f"File size: {get_workshop_file_size(workshop_id, raw=True)}")

        if not destination_folder:
            show_message("Error", "Please select a destination folder.")
            return

        if not steamcmd_path:
            show_message("Error", "Please enter the SteamCMD path.")
            return

        self.button_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.button_download.setEnabled(False)

        self.download_thread = DownloadThread(workshop_id, destination_folder, self.progress_bar, self.label_speed)
        self.download_thread.finished.connect(self.on_download_finished)
        self.download_thread.start()

    def stop_download(self):
        global stopped
        stopped = True

        subprocess.run(['taskkill', '/F', '/IM', 'steamcmd.exe'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.terminate()

        self.button_download.setEnabled(True)
        self.button_stop.setEnabled(False)
        self.progress_bar.setValue(0)
        self.label_speed.setText(f"Network Speed: {0:.2f} KB/s")
        self.label_file_size.setText(f"File size: 0KB")

    def open_BOIII_browser(self):
        selected_folder = QFileDialog.getExistingDirectory(self, "Select BOIII Folder", "")
        if selected_folder:
            self.edit_destination_folder.setText(selected_folder)

    def open_steamcmd_path_browser(self):
        selected_folder = QFileDialog.getExistingDirectory(self, "Select SteamCMD Folder", "")
        if selected_folder:
            self.edit_steamcmd_path.setText(selected_folder)

    def on_download_finished(self):
        self.button_download.setEnabled(True)
        self.progress_bar.setValue(0)
        self.label_speed.setText(f"Network Speed: {0:.2f} KB/s")
        self.label_file_size.setText(f"File size: 0KB")
        self.button_stop.setEnabled(False)
        self.save_config(self.edit_destination_folder.text(), self.edit_steamcmd_path.text())

    def open_browser(self):
        link = "https://steamcommunity.com/app/311210/workshop/"
        webbrowser.open(link)

    def load_config(self):
        config = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE_PATH):
            config.read(CONFIG_FILE_PATH)
            destination_folder = config.get("Settings", "DestinationFolder", fallback="")
            steamcmd_path = config.get("Settings", "SteamCMDPath", fallback=cwd())
            self.edit_destination_folder.setText(destination_folder)
            self.edit_steamcmd_path.setText(steamcmd_path)
        else:
            create_default_config()

    def save_config(self, destination_folder, steamcmd_path):
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE_PATH)
        config.set("Settings", "DestinationFolder", destination_folder)
        config.set("Settings", "SteamCMDPath", steamcmd_path)
        with open(CONFIG_FILE_PATH, "w") as config_file:
            config.write(config_file)

    def show_map_info(self):
        workshop_id = self.edit_workshop_id.text()

        if not workshop_id:
            QMessageBox.warning(self, "Warning", "Please enter a Workshop ID first.")
            return

        if not workshop_id.isdigit():
            QMessageBox.warning(self, "Warning", "Please enter a valid Workshop ID.")
            return

        self.label_file_size.setText(f"File size: {get_workshop_file_size(workshop_id, raw=True)}")
        try:
            url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
            response = requests.get(url)
            response.raise_for_status()
            content = response.text

            soup = BeautifulSoup(content, "html.parser")

            try:
                map_mod_type = soup.find("div", class_="rightDetailsBlock").text.strip()
                map_name = soup.find("div", class_="workshopItemTitle").text.strip()
                map_size = soup.find("div", class_="detailsStatRight").text.strip()
                stars_div = soup.find("div", class_="fileRatingDetails")
                stars = stars_div.find("img")["src"]
            except:
                QMessageBox.warning(self, "Warning", "Please enter a valid Workshop ID.")
                return

            try:
                preview_image_element = soup.find("img", id="previewImage")
                workshop_item_image_url = preview_image_element["src"]
            except:
                preview_image_element = soup.find("img", id="previewImageMain")
                workshop_item_image_url = preview_image_element["src"]

            image_response = requests.get(workshop_item_image_url)
            image_response.raise_for_status()

            stars_response = requests.get(stars)
            stars_response.raise_for_status()

            pixmap = QPixmap()
            pixmap.loadFromData(image_response.content)

            pixmap_stars = QPixmap()
            pixmap_stars.loadFromData(stars_response.content)

            label = QLabel(self)
            label.setPixmap(pixmap)
            label.setAlignment(Qt.AlignCenter)

            label_stars = QLabel(self)
            label_stars.setPixmap(pixmap_stars)
            label_stars.setAlignment(Qt.AlignCenter)

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Map/Mod Information")
            msg_box.setIconPixmap(pixmap)
            msg_box.setText(f"Name: {map_name}\nType: {map_mod_type}\nSize: {map_size}")

            layout = QVBoxLayout()
            layout.addWidget(label)
            layout.addWidget(label_stars)
            msg_box.setLayout(layout)

            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.setDetailedText(f"Stars: {stars}\nLink: {url}")

            msg_box.exec_()

        except requests.exceptions.RequestException as e:
            QMessageBox.warning(self, "Error", f"Failed to fetch map information.\nError: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    qdarktheme.setup_theme()

    if not os.path.exists(CONFIG_FILE_PATH):
        create_default_config()

    window = WorkshopDownloaderApp()
    window.show()

    sys.exit(app.exec_())
