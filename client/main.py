from __future__ import annotations

import sys
from datetime import datetime

from PySide6.QtCore import Qt, QThreadPool, QSettings, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from client.api import ApiTask, start_api_task
from client.auth_store import account_key, delete_token, load_token, save_token
from client.socket_client import ChannelSocket

DEFAULT_API = "http://127.0.0.1:8000"

STYLE = """
QWidget { background: #171923; color: #e8eaf2; font-family: Segoe UI; font-size: 14px; }
QLineEdit, QTextEdit, QListWidget, QComboBox { background: #222635; border: 1px solid #34394c; border-radius: 7px; padding: 9px; selection-background-color: #5865f2; }
QPushButton { background: #5865f2; border: none; border-radius: 7px; padding: 10px 14px; font-weight: 600; }
QPushButton:hover { background: #6975ff; }
QPushButton#subtle { background: #2a2f40; }
QPushButton#subtle:hover { background: #363c50; }
QLabel#title { font-size: 22px; font-weight: 700; }
QLabel#muted { color: #aab0c2; }
QListWidget::item { padding: 8px; }
QSplitter::handle { background: #292e3d; }
"""

LIGHT_STYLE = """
QWidget { background: #f3f5fa; color: #202334; font-family: Segoe UI; font-size: 14px; }
QLineEdit, QTextEdit, QListWidget, QComboBox { background: #ffffff; border: 1px solid #d5d9e5; border-radius: 7px; padding: 9px; selection-background-color: #5865f2; }
QPushButton { background: #5865f2; color: #ffffff; border: none; border-radius: 7px; padding: 10px 14px; font-weight: 600; }
QPushButton:hover { background: #6975ff; }
QPushButton#subtle { background: #e5e8f1; color: #202334; }
QPushButton#subtle:hover { background: #d8ddec; }
QLabel#title { font-size: 22px; font-weight: 700; }
QLabel#muted { color: #626a80; }
QListWidget::item { padding: 8px; }
QSplitter::handle { background: #dce0eb; }
QTabWidget::pane { border: 1px solid #d5d9e5; border-radius: 8px; }
QTabBar::tab { background: #e5e8f1; padding: 9px 18px; margin-right: 4px; border-radius: 6px; }
QTabBar::tab:selected { background: #5865f2; color: white; }
"""


def apply_theme(theme: str):
    QApplication.instance().setStyleSheet(LIGHT_STYLE if theme == "light" else STYLE)


class LoginWindow(QWidget):
    def __init__(self, on_authenticated):
        super().__init__()
        self.on_authenticated = on_authenticated
        self.pool = QThreadPool.globalInstance()
        self._task_relays = set()
        self.api_url = QLineEdit(DEFAULT_API)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Nazwa użytkownika")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Hasło (min. 12 znaków przy rejestracji)")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.remember = QCheckBox("Zapamiętaj mnie na tym komputerze")
        self.remember.setChecked(True)
        self.status = QLabel("Backend musi działać pod adresem http://127.0.0.1:8000")
        self.status.setObjectName("muted")
        self.login_btn = QPushButton("Zaloguj się")
        self.register_btn = QPushButton("Utwórz konto")
        self.login_btn.clicked.connect(self.login)
        self.register_btn.clicked.connect(self.register)

        form = QFormLayout()
        form.addRow("Adres backendu", self.api_url)
        form.addRow("Nazwa użytkownika", self.username)
        form.addRow("Hasło", self.password)
        form.addRow("", self.remember)
        buttons = QHBoxLayout()
        buttons.addWidget(self.login_btn)
        buttons.addWidget(self.register_btn)
        card = QVBoxLayout()
        title = QLabel("Soko Chat")
        title.setObjectName("title")
        card.addWidget(title)
        card.addWidget(QLabel("Zaloguj się lub utwórz konto, aby kontynuować."))
        card.addSpacing(10)
        card.addLayout(form)
        card.addLayout(buttons)
        card.addWidget(self.status)
        container = QWidget()
        container.setLayout(card)
        container.setMaximumWidth(520)
        layout = QVBoxLayout(self)
        layout.addStretch()
        layout.addWidget(container, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()

    def request(self, method, path, payload, callback, token=None):
        task = ApiTask(method, self.api_url.text().strip(), path, token=token, payload=payload)
        start_api_task(self.pool, self, task, callback)
        self.login_btn.setEnabled(False)
        self.register_btn.setEnabled(False)

    def finished(self, result):
        self.login_btn.setEnabled(True)
        self.register_btn.setEnabled(True)
        return result.get("ok", False)

    @Slot(object)
    def _release_task_relay(self, relay):
        self._task_relays.discard(relay)

    def register(self):
        username, password = self.username.text().strip(), self.password.text()
        if len(password) < 12:
            self.status.setText("Hasło rejestracyjne musi mieć co najmniej 12 znaków.")
            return
        self.status.setText("Tworzę konto…")

        def done(result):
            if not self.finished(result):
                self.status.setText(result.get("error", "Nie udało się utworzyć konta."))
                return
            self.status.setText("Konto utworzone. Teraz zaloguj się.")

        self.request("POST", "/auth/register", {"username": username, "password": password}, done)

    def login(self):
        username, password = self.username.text().strip(), self.password.text()
        if not username or not password:
            self.status.setText("Wpisz nazwę użytkownika i hasło.")
            return
        self.status.setText("Loguję…")

        def done(result):
            if not self.finished(result):
                self.status.setText(result.get("error", "Logowanie nie powiodło się."))
                return
            api_url = self.api_url.text().strip().rstrip("/")
            token = result["data"]["access_token"]
            prefs = QSettings("SokoChat", "SokoChat")
            previous_key = prefs.value("auth/account_key", "")
            if previous_key and previous_key != account_key(api_url, username):
                delete_token(previous_key)
            try:
                if self.remember.isChecked():
                    save_token(account_key(api_url, username), token)
                    prefs.setValue("auth/api_url", api_url)
                    prefs.setValue("auth/username", username)
                    prefs.setValue("auth/account_key", account_key(api_url, username))
                else:
                    delete_token(account_key(api_url, username))
                    prefs.remove("auth/api_url")
                    prefs.remove("auth/username")
                    prefs.remove("auth/account_key")
            except Exception:
                QMessageBox.warning(self, "Sesja niezapamiętana", "Logowanie się powiodło, ale Windows nie pozwolił bezpiecznie zapisać sesji. Następnym razem zaloguj się ponownie.")
            self.on_authenticated(api_url, token, username)

        self.request("POST", "/auth/login", {"username": username, "password": password}, done)

    def restore_session(self, api_url: str, username: str, token: str):
        self.api_url.setText(api_url)
        self.username.setText(username)
        self.status.setText("Przywracam zapamiętaną sesję…")

        def done(result):
            self.finished(result)
            if result.get("ok"):
                self.on_authenticated(api_url, token, username)
                return
            if result.get("status") in (401, 404):
                prefs = QSettings("SokoChat", "SokoChat")
                delete_token(account_key(api_url, username))
                prefs.remove("auth/api_url")
                prefs.remove("auth/username")
                prefs.remove("auth/account_key")
                self.status.setText("Zapisana sesja wygasła. Zaloguj się ponownie.")
            else:
                self.status.setText(result.get("error", "Nie udało się przywrócić sesji. Zaloguj się ponownie."))

        self.request("GET", "/users/me", None, done, token=token)


class MainWindow(QMainWindow):
    def __init__(self, api_url: str, token: str, on_logout):
        super().__init__()
        self.api_url = api_url
        self.token = token
        self.on_logout = on_logout
        self.pool = QThreadPool.globalInstance()
        self._task_relays = set()
        self.socket: ChannelSocket | None = None
        self.current_channel: str | None = None
        self.messages_seen: set[str] = set()
        self.prefs = QSettings("SokoChat", "SokoChat")
        self.setWindowTitle("Soko Chat")
        self.resize(1120, 720)

        self.servers = QListWidget()
        self.channels = QListWidget()
        self.members = QListWidget()
        self.messages = QListWidget()
        self.messages.setWordWrap(True)
        self.composer = QLineEdit()
        self.composer.setPlaceholderText("Napisz wiadomość…")
        self.composer.returnPressed.connect(self.send_message)
        self.send_btn = QPushButton("Wyślij")
        self.send_btn.clicked.connect(self.send_message)
        self.status = QLabel("Połączono")
        self.status.setObjectName("muted")

        add_server = QPushButton("+ Serwer")
        add_server.setObjectName("subtle")
        add_server.clicked.connect(self.create_server)
        join_server = QPushButton("Dołącz z kodem")
        join_server.setObjectName("subtle")
        join_server.clicked.connect(self.join_server)
        invite = QPushButton("Zaproś osobę")
        invite.setObjectName("subtle")
        invite.clicked.connect(self.create_invite)
        refresh = QPushButton("Odśwież")
        refresh.setObjectName("subtle")
        refresh.clicked.connect(self.load_servers)
        logout = QPushButton("Wyloguj")
        logout.setObjectName("subtle")
        logout.clicked.connect(self.logout)
        settings_button = QPushButton("⚙ Ustawienia")
        settings_button.setObjectName("subtle")
        settings_button.clicked.connect(self.open_settings)

        server_panel = QWidget()
        server_layout = QVBoxLayout(server_panel)
        server_layout.addWidget(QLabel("Serwery"))
        server_layout.addWidget(self.servers)
        server_layout.addWidget(add_server)
        server_layout.addWidget(join_server)
        server_layout.addWidget(invite)
        server_layout.addWidget(refresh)

        channel_panel = QWidget()
        channel_layout = QVBoxLayout(channel_panel)
        channel_layout.addWidget(QLabel("Kanały"))
        channel_layout.addWidget(self.channels)

        member_panel = QWidget()
        member_layout = QVBoxLayout(member_panel)
        member_layout.addWidget(QLabel("Członkowie"))
        member_layout.addWidget(self.members)

        chat_panel = QWidget()
        chat_layout = QVBoxLayout(chat_panel)
        top = QHBoxLayout()
        self.channel_title = QLabel("Wybierz kanał")
        self.channel_title.setObjectName("title")
        top.addWidget(self.channel_title)
        top.addStretch()
        top.addWidget(self.status)
        chat_layout.addLayout(top)
        chat_layout.addWidget(self.messages, 1)
        compose = QHBoxLayout()
        compose.addWidget(self.composer, 1)
        compose.addWidget(self.send_btn)
        chat_layout.addLayout(compose)

        splitter = QSplitter()
        splitter.addWidget(server_panel)
        splitter.addWidget(channel_panel)
        splitter.addWidget(chat_panel)
        splitter.addWidget(member_panel)
        splitter.setSizes([190, 205, 555, 190])

        self.friends_list = QListWidget()
        self.requests_list = QListWidget()
        self.friend_search = QLineEdit()
        self.friend_search.setPlaceholderText("Wpisz dokładną nazwę użytkownika Soko Chat")
        add_friend = QPushButton("Dodaj znajomego")
        add_friend.clicked.connect(self.add_friend)
        refresh_friends = QPushButton("Odśwież")
        refresh_friends.setObjectName("subtle")
        refresh_friends.clicked.connect(self.load_friends)
        self.friend_status = QLabel("Znajomi widoczni tutaj mają konta Soko Chat.")
        self.friend_status.setObjectName("muted")
        friend_toolbar = QHBoxLayout()
        friend_toolbar.addWidget(self.friend_search, 1)
        friend_toolbar.addWidget(add_friend)
        friend_toolbar.addWidget(refresh_friends)

        self.accept_request_btn = QPushButton("Akceptuj zaproszenie")
        self.reject_request_btn = QPushButton("Odrzuć")
        self.remove_friend_btn = QPushButton("Usuń znajomego")
        self.accept_request_btn.clicked.connect(self.accept_friend)
        self.reject_request_btn.clicked.connect(self.reject_friend)
        self.remove_friend_btn.clicked.connect(self.remove_friend)
        request_actions = QHBoxLayout()
        request_actions.addWidget(self.accept_request_btn)
        request_actions.addWidget(self.reject_request_btn)
        friend_actions = QHBoxLayout()
        friend_actions.addWidget(self.remove_friend_btn)

        friends_page = QWidget()
        friends_layout = QVBoxLayout(friends_page)
        friends_title = QLabel("Znajomi")
        friends_title.setObjectName("title")
        friends_layout.addWidget(friends_title)
        friends_layout.addLayout(friend_toolbar)
        friends_layout.addWidget(self.friend_status)
        friends_columns = QHBoxLayout()
        friends_column = QVBoxLayout()
        friends_column.addWidget(QLabel("Znajomi na Soko Chat"))
        friends_column.addWidget(self.friends_list, 1)
        friends_column.addLayout(friend_actions)
        requests_column = QVBoxLayout()
        requests_column.addWidget(QLabel("Otrzymane zaproszenia"))
        requests_column.addWidget(self.requests_list, 1)
        requests_column.addLayout(request_actions)
        friends_columns.addLayout(friends_column, 1)
        friends_columns.addLayout(requests_column, 1)
        friends_layout.addLayout(friends_columns, 1)

        self.tabs = QTabWidget()
        self.tabs.addTab(splitter, "Serwery")
        self.tabs.addTab(friends_page, "Znajomi")
        self.tabs.currentChanged.connect(lambda index: self.load_friends() if index == 1 else None)

        app_body = QWidget()
        app_layout = QVBoxLayout(app_body)
        app_header = QHBoxLayout()
        brand = QLabel("Soko Chat")
        brand.setObjectName("title")
        beta_badge = QLabel("BETA")
        beta_badge.setObjectName("muted")
        app_header.addWidget(brand)
        app_header.addWidget(beta_badge)
        app_header.addStretch()
        app_header.addWidget(settings_button)
        app_header.addWidget(logout)
        app_layout.addLayout(app_header)
        app_layout.addWidget(self.tabs, 1)
        self.setCentralWidget(app_body)
        self.servers.currentItemChanged.connect(self.server_selected)
        self.channels.currentItemChanged.connect(self.channel_selected)
        self.load_servers()

    def request(self, method, path, payload=None, params=None, callback=None):
        task = ApiTask(method, self.api_url, path, token=self.token, payload=payload, params=params)
        start_api_task(self.pool, self, task, callback or self.show_request_error)

    @Slot(object)
    def _release_task_relay(self, relay):
        self._task_relays.discard(relay)

    def show_request_error(self, result):
        if not result.get("ok"):
            self.status.setText(result.get("error", "Błąd połączenia"))

    def load_friends(self):
        self.friend_status.setText("Pobieram listę znajomych…")
        self.request("GET", "/friends", callback=self.populate_friends)
        self.request("GET", "/friends/requests", callback=self.populate_friend_requests)

    def populate_friends(self, result):
        if not result.get("ok"):
            self.friend_status.setText(result.get("error", "Nie udało się pobrać znajomych."))
            return
        self.friends_list.clear()
        for friend in result["data"]:
            item = QListWidgetItem(friend["username"])
            item.setData(Qt.ItemDataRole.UserRole, friend["id"])
            self.friends_list.addItem(item)
        self.friend_status.setText(f"Znajomi na Soko Chat: {len(result['data'])}")

    def populate_friend_requests(self, result):
        if not result.get("ok"):
            self.friend_status.setText(result.get("error", "Nie udało się pobrać zaproszeń."))
            return
        self.requests_list.clear()
        for request in result["data"]:
            item = QListWidgetItem(request["username"])
            item.setData(Qt.ItemDataRole.UserRole, request["id"])
            self.requests_list.addItem(item)

    def add_friend(self):
        username = self.friend_search.text().strip()
        if not username:
            self.friend_status.setText("Wpisz nazwę użytkownika Soko Chat.")
            return

        def found(result):
            if not result.get("ok"):
                self.friend_status.setText(result.get("error", "Nie znaleziono użytkownika."))
                return
            target = result["data"]
            self.request(
                "POST",
                f"/friends/{target['id']}/requests",
                callback=lambda sent: self.friend_request_sent(sent, target["username"]),
            )

        self.request("GET", "/users/lookup", params={"username": username}, callback=found)

    def friend_request_sent(self, result, username):
        if not result.get("ok"):
            self.friend_status.setText(result.get("error", "Nie udało się wysłać zaproszenia."))
            return
        self.friend_search.clear()
        self.friend_status.setText(f"Wysłano zaproszenie do {username}.")

    def accept_friend(self):
        item = self.requests_list.currentItem()
        if not item:
            self.friend_status.setText("Wybierz zaproszenie do zaakceptowania.")
            return
        user_id = item.data(Qt.ItemDataRole.UserRole)

        def done(result):
            if not result.get("ok"):
                self.friend_status.setText(result.get("error", "Nie udało się zaakceptować zaproszenia."))
                return
            self.load_friends()

        self.request("POST", f"/friends/{user_id}/accept", callback=done)

    def reject_friend(self):
        item = self.requests_list.currentItem()
        if not item:
            self.friend_status.setText("Wybierz zaproszenie do odrzucenia.")
            return
        self.remove_friend_id(item.data(Qt.ItemDataRole.UserRole))

    def remove_friend(self):
        item = self.friends_list.currentItem()
        if not item:
            self.friend_status.setText("Wybierz znajomego z listy.")
            return
        self.remove_friend_id(item.data(Qt.ItemDataRole.UserRole))

    def remove_friend_id(self, user_id):
        def done(result):
            if not result.get("ok"):
                self.friend_status.setText(result.get("error", "Nie udało się usunąć znajomości."))
                return
            self.load_friends()

        self.request("DELETE", f"/friends/{user_id}", callback=done)

    def open_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Ustawienia Soko Chat")
        dialog.setMinimumWidth(340)
        theme = QComboBox()
        theme.addItem("Ciemny", "dark")
        theme.addItem("Jasny", "light")
        current = self.prefs.value("appearance/theme", "dark")
        theme.setCurrentIndex(1 if current == "light" else 0)
        close_button = QPushButton("Gotowe")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Wygląd aplikacji"))
        layout.addWidget(theme)
        layout.addWidget(close_button)

        def set_theme():
            value = theme.currentData()
            self.prefs.setValue("appearance/theme", value)
            apply_theme(value)

        theme.currentIndexChanged.connect(set_theme)
        close_button.clicked.connect(dialog.accept)
        dialog.exec()

    def load_servers(self):
        self.status.setText("Pobieram serwery…")

        def done(result):
            if not result.get("ok"):
                self.show_request_error(result)
                return
            selected_id = self.servers.currentItem().data(Qt.ItemDataRole.UserRole) if self.servers.currentItem() else None
            self.servers.clear()
            for server in result["data"]:
                from PySide6.QtWidgets import QListWidgetItem
                item = QListWidgetItem(server["name"])
                item.setData(Qt.ItemDataRole.UserRole, server["id"])
                self.servers.addItem(item)
                if server["id"] == selected_id:
                    self.servers.setCurrentItem(item)
            self.status.setText(f"{len(result['data'])} serwer(ów)")
            if self.servers.count() and not self.servers.currentItem():
                self.servers.setCurrentRow(0)
            elif not self.servers.count():
                self.channels.clear()
                self.messages.clear()
                self.channel_title.setText("Utwórz serwer, aby zacząć")

        self.request("GET", "/servers", callback=done)

    def create_server(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Nowy serwer")
        name = QLineEdit()
        name.setPlaceholderText("Nazwa serwera")
        create = QPushButton("Utwórz")
        cancel = QPushButton("Anuluj")
        buttons = QHBoxLayout()
        buttons.addWidget(create)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Podaj nazwę nowego serwera:"))
        layout.addWidget(name)
        layout.addLayout(buttons)
        cancel.clicked.connect(dialog.reject)

        def submit():
            value = name.text().strip()
            if not value:
                name.setFocus()
                return
            create.setEnabled(False)

            def done(result):
                create.setEnabled(True)
                if not result.get("ok"):
                    QMessageBox.warning(dialog, "Nie udało się utworzyć serwera", result.get("error", "Błąd serwera"))
                    return
                dialog.accept()
                self.load_servers()

            self.request("POST", "/servers", payload={"name": value}, callback=done)

        create.clicked.connect(submit)
        dialog.exec()

    def server_selected(self, current, _previous):
        if not current:
            return
        server_id = current.data(Qt.ItemDataRole.UserRole)
        self.channels.clear()
        self.members.clear()
        self.request("GET", f"/servers/{server_id}/channels", callback=lambda r: self.populate_channels(r))
        self.request("GET", f"/servers/{server_id}/members", callback=lambda r: self.populate_members(r))

    def populate_members(self, result):
        if not result.get("ok"):
            self.show_request_error(result)
            return
        self.members.clear()
        for member in result["data"]:
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(member["username"])
            item.setData(Qt.ItemDataRole.UserRole, member["id"])
            self.members.addItem(item)

    def create_invite(self):
        current = self.servers.currentItem()
        if not current:
            self.status.setText("Najpierw wybierz serwer.")
            return
        server_id = current.data(Qt.ItemDataRole.UserRole)

        def done(result):
            if not result.get("ok"):
                QMessageBox.warning(self, "Nie udało się utworzyć zaproszenia", result.get("error", "Błąd serwera"))
                return
            code = result["data"]["invite_code"]
            dialog = QDialog(self)
            dialog.setWindowTitle("Zaproszenie do Soko Chat")
            dialog.setMinimumWidth(430)
            code_field = QLineEdit(code)
            code_field.setReadOnly(True)
            copy_button = QPushButton("Kopiuj kod")
            close_button = QPushButton("Gotowe")
            buttons = QHBoxLayout()
            buttons.addWidget(copy_button)
            buttons.addWidget(close_button)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("Przekaż ten kod osobie, którą chcesz zaprosić. Kod działa przez 7 dni."))
            layout.addWidget(code_field)
            layout.addLayout(buttons)
            copy_button.clicked.connect(lambda: QApplication.clipboard().setText(code))
            copy_button.clicked.connect(lambda: copy_button.setText("Skopiowano"))
            close_button.clicked.connect(dialog.accept)
            dialog.exec()

        self.request("POST", f"/servers/{server_id}/invites", callback=done)

    def join_server(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Dołącz do serwera")
        code = QLineEdit()
        code.setPlaceholderText("Wklej kod zaproszenia")
        join_button = QPushButton("Dołącz")
        cancel_button = QPushButton("Anuluj")
        buttons = QHBoxLayout()
        buttons.addWidget(join_button)
        buttons.addWidget(cancel_button)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Wpisz kod zaproszenia do Soko Chat:"))
        layout.addWidget(code)
        layout.addLayout(buttons)
        cancel_button.clicked.connect(dialog.reject)

        def submit():
            value = code.text().strip()
            if not value:
                return
            join_button.setEnabled(False)

            def done(result):
                join_button.setEnabled(True)
                if not result.get("ok"):
                    QMessageBox.warning(dialog, "Nie udało się dołączyć", result.get("error", "Nieprawidłowe zaproszenie"))
                    return
                dialog.accept()
                self.load_servers()
                self.status.setText(f"Dołączono do: {result['data']['server_name']}")

            self.request("POST", f"/invites/{value}/join", callback=done)

        join_button.clicked.connect(submit)
        dialog.exec()

    def populate_channels(self, result):
        if not result.get("ok"):
            self.show_request_error(result)
            return
        self.channels.clear()
        for channel in result["data"]:
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem("#  " + channel["name"])
            item.setData(Qt.ItemDataRole.UserRole, channel["id"])
            self.channels.addItem(item)
        if self.channels.count():
            self.channels.setCurrentRow(0)

    def channel_selected(self, current, _previous):
        if not current:
            return
        self.stop_socket()
        self.current_channel = current.data(Qt.ItemDataRole.UserRole)
        self.channel_title.setText(current.text())
        self.messages.clear()
        self.messages_seen.clear()
        channel_id = self.current_channel
        self.request("GET", f"/channels/{channel_id}/messages", callback=lambda r: self.populate_messages(r, channel_id))
        self.socket = ChannelSocket(self.api_url, channel_id, self.token)
        self.socket.received.connect(self.receive_event)
        self.socket.state_changed.connect(self.status.setText)
        self.socket.start()

    def populate_messages(self, result, channel_id):
        if channel_id != self.current_channel:
            return
        if not result.get("ok"):
            self.show_request_error(result)
            return
        for message in result["data"]:
            self.add_message(message)
        self.messages.scrollToBottom()

    def add_message(self, message):
        if message["id"] in self.messages_seen:
            return
        self.messages_seen.add(message["id"])
        created = message.get("created_at", "")
        try:
            created = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
        except Exception:
            created = ""
        edited = " (edytowano)" if message.get("edited_at") else ""
        self.messages.addItem(f"{created}  {message['author_id'][:8]}:  {message['content']}{edited}")
        self.messages.scrollToBottom()

    def receive_event(self, event):
        if event.get("type") == "message" and event.get("message"):
            self.add_message(event["message"])
        elif event.get("type") == "message_edited" and event.get("message"):
            self.reload_history()
        elif event.get("type") == "message_deleted":
            self.reload_history()

    def reload_history(self):
        channel_id = self.current_channel
        if not channel_id:
            return
        self.request("GET", f"/channels/{channel_id}/messages", callback=lambda r: self.replace_history(r, channel_id))

    def replace_history(self, result, channel_id):
        if not result.get("ok") or channel_id != self.current_channel:
            return
        self.messages.clear()
        self.messages_seen.clear()
        for message in result["data"]:
            self.add_message(message)

    def send_message(self):
        content = self.composer.text().strip()
        channel_id = self.current_channel
        if not content or not channel_id:
            return
        self.send_btn.setEnabled(False)

        def done(result):
            self.send_btn.setEnabled(True)
            if not result.get("ok"):
                self.show_request_error(result)
                return
            self.composer.clear()
            self.add_message(result["data"])

        self.request("POST", f"/channels/{channel_id}/messages", payload={"content": content}, callback=done)

    def stop_socket(self):
        if self.socket and self.socket.isRunning():
            self.socket.stop()
            self.socket.wait(2500)
        self.socket = None

    def logout(self):
        self.stop_socket()
        self.request("POST", "/auth/logout", callback=lambda _r: self.on_logout())

    def closeEvent(self, event):
        self.stop_socket()
        super().closeEvent(event)


class AppController:
    def __init__(self):
        self.prefs = QSettings("SokoChat", "SokoChat")
        self.saved_account_key = self.prefs.value("auth/account_key", "")
        self.login_window = LoginWindow(self.open_main)
        self.main_window: MainWindow | None = None
        self.login_window.show()
        api_url = self.prefs.value("auth/api_url", "")
        username = self.prefs.value("auth/username", "")
        if api_url and username and self.saved_account_key:
            try:
                token = load_token(self.saved_account_key)
            except Exception:
                token = None
            if token:
                self.login_window.remember.setChecked(True)
                self.login_window.restore_session(api_url, username, token)

    def open_main(self, api_url, token, username):
        self.saved_account_key = self.prefs.value("auth/account_key", "")
        self.login_window.hide()
        self.main_window = MainWindow(api_url, token, self.return_to_login)
        self.main_window.show()
        QMessageBox.information(
            self.main_window,
            "Soko Chat — beta",
            f"Witaj, {username}! Soko Chat jest w wersji beta. Mogą występować błędy.",
        )

    def return_to_login(self):
        if self.saved_account_key:
            delete_token(self.saved_account_key)
        self.prefs.remove("auth/api_url")
        self.prefs.remove("auth/username")
        self.prefs.remove("auth/account_key")
        self.saved_account_key = ""
        if self.main_window:
            self.main_window.close()
            self.main_window.deleteLater()
            self.main_window = None
        self.login_window.status.setText("Wylogowano.")
        self.login_window.show()


def main():
    app = QApplication(sys.argv)
    prefs = QSettings("SokoChat", "SokoChat")
    apply_theme(prefs.value("appearance/theme", "dark"))
    controller = AppController()
    app._controller = controller
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
