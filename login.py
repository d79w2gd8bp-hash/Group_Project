from typing import Any, List

from customtkinter import (
    CTk,
    CTkButton,
    CTkEntry,
    CTkFrame,
    CTkImage,
    CTkLabel,
    set_appearance_mode,
    set_default_color_theme,
)
from PIL import Image

from main import (
    ACCOUNTS_PATH,
    LOG_PATH,
    LOGIN_LOGO_PATH,
    UI_FONT_FAMILY,
    UI_COLORS,
    WINDOW_TITLE,
    AccountManager,
    AuditLogger,
    VotingApp,
    apply_window_icon,
    fit_window_to_screen,
    start_fade_in,
)


class LoginApp(CTk):
    def __init__(self):
        super().__init__()
        set_appearance_mode("dark")
        set_default_color_theme("blue")
        self.title(f"Login • {WINDOW_TITLE}")
        apply_window_icon(self)
        self.configure(fg_color=UI_COLORS["background"])
        self.window_width, self.window_height = fit_window_to_screen(
            self, 1120, 720, 900, 600, horizontal_margin=80, vertical_margin=100
        )

        self.account_manager = AccountManager(ACCOUNTS_PATH)
        self.audit_logger = AuditLogger(LOG_PATH)
        self.authenticated_account = None
        self.login_username_entry = None
        self._build_ui()
        self._show_login()
        start_fade_in(self)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=5)
        self.grid_columnconfigure(1, weight=4)
        self.grid_rowconfigure(0, weight=1)

        brand_panel = CTkFrame(self, fg_color="#0F2A5F", corner_radius=0)
        brand_panel.grid(row=0, column=0, sticky="nsew")
        brand_panel.grid_columnconfigure(0, weight=1)
        brand_panel.grid_rowconfigure(0, weight=1)
        brand_panel.grid_rowconfigure(5, weight=1)

        brand_header = CTkFrame(brand_panel, fg_color="transparent")
        brand_header.grid(row=1, column=0, sticky="ew", padx=46, pady=(0, 18))
        brand_header.grid_columnconfigure(1, weight=1)

        if LOGIN_LOGO_PATH.exists():
            logo_size = max(96, min(128, int(self.window_height * 0.18)))
            logo_source = Image.open(LOGIN_LOGO_PATH).convert("RGBA")
            self.login_logo = CTkImage(
                light_image=logo_source,
                dark_image=logo_source,
                size=(logo_size, logo_size),
            )
            logo_card = CTkFrame(
                brand_header, fg_color="#FFFFFF", corner_radius=20,
                border_width=1, border_color="#DBEAFE",
            )
            logo_card.grid(row=0, column=0, sticky="w")
            CTkLabel(logo_card, text="", image=self.login_logo).pack(padx=8, pady=8)

        CTkLabel(
            brand_header,
            text="မဲစာရင်းအချက်အလက်များ\nစိစစ်ရေးစနစ်",
            font=(UI_FONT_FAMILY, 25, "bold"),
            justify="left",
            text_color="#FFFFFF",
            anchor="w",
            wraplength=max(230, int(self.window_width * 0.27)),
        ).grid(row=0, column=1, sticky="w", padx=(22, 0))
        CTkLabel(
            brand_panel,
            text="နိုင်ငံသားအချက်အလက်နှင့် မဲပေးမှုအခြေအနေကို\nလုံခြုံစွာ စစ်ဆေးစီမံနိုင်ပါသည်။",
            font=(UI_FONT_FAMILY, 15),
            justify="left",
            text_color="#BFDBFE",
            anchor="w",
            wraplength=max(330, int(self.window_width * 0.43)),
        ).grid(row=2, column=0, sticky="w", padx=58, pady=(10, 24))
        CTkLabel(
            brand_panel,
            text="SECURE  •  ACCURATE  •  ROLE BASED",
            font=(UI_FONT_FAMILY, 11, "bold"),
            text_color="#60A5FA",
        ).grid(row=3, column=0, sticky="w", padx=58)

        form_area = CTkFrame(self, fg_color=UI_COLORS["background"], corner_radius=0)
        form_area.grid(row=0, column=1, sticky="nsew")
        form_area.grid_columnconfigure(0, weight=1)
        form_area.grid_rowconfigure(0, weight=1)

        self.auth_card = CTkFrame(
            form_area,
            width=420,
            fg_color=UI_COLORS["surface"],
            corner_radius=18,
            border_width=1,
            border_color=UI_COLORS["border"],
        )
        self.auth_card.grid(row=0, column=0, padx=32, pady=32, sticky="ew")
        self.auth_card.grid_columnconfigure(0, weight=1)

        tabs = CTkFrame(self.auth_card, fg_color=UI_COLORS["surface_alt"], corner_radius=10)
        tabs.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 18))
        tabs.grid_columnconfigure(0, weight=1)
        tabs.grid_columnconfigure(1, weight=1)
        self.login_tab_button = CTkButton(
            tabs, text="Login", height=38, command=self._show_login,
            fg_color=UI_COLORS["primary"], hover_color=UI_COLORS["primary_hover"],
            font=(UI_FONT_FAMILY, 12, "bold"),
        )
        self.login_tab_button.grid(row=0, column=0, sticky="ew", padx=(4, 2), pady=4)
        self.signup_tab_button = CTkButton(
            tabs, text="Sign Up", height=38, command=self._show_signup,
            fg_color="transparent", hover_color=UI_COLORS["primary_hover"],
            font=(UI_FONT_FAMILY, 12, "bold"),
        )
        self.signup_tab_button.grid(row=0, column=1, sticky="ew", padx=(2, 4), pady=4)

        self.form_frame = CTkFrame(self.auth_card, fg_color="transparent")
        self.form_frame.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 28))
        self.form_frame.grid_columnconfigure(0, weight=1)

    def _clear_form(self):
        for child in self.form_frame.winfo_children():
            child.destroy()

    def _field(self, row: int, label: str, placeholder: str, show: str = "") -> CTkEntry:
        CTkLabel(
            self.form_frame, text=label, font=(UI_FONT_FAMILY, 12, "bold"),
            text_color=UI_COLORS["text"], anchor="w", height=30,
        ).grid(row=row, column=0, sticky="ew", pady=(9, 5))
        entry = CTkEntry(
            self.form_frame, placeholder_text=placeholder, show=show, height=44,
            fg_color=UI_COLORS["surface_alt"], border_color=UI_COLORS["border"],
            font=(UI_FONT_FAMILY, 12),
        )
        entry.grid(row=row + 1, column=0, sticky="ew", pady=(0, 3))
        return entry

    def _message_label(self, row: int) -> CTkLabel:
        label = CTkLabel(
            self.form_frame, text="", wraplength=340, justify="left",
            text_color="#FCA5A5", anchor="w", font=(UI_FONT_FAMILY, 11),
        )
        label.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        return label

    def _show_login(self, preset_username: str = ""):
        self._clear_form()
        self.login_tab_button.configure(fg_color=UI_COLORS["primary"])
        self.signup_tab_button.configure(fg_color="transparent")

        CTkLabel(
            self.form_frame, text="ကြိုဆိုပါသည်", font=(UI_FONT_FAMILY, 25, "bold"),
            text_color=UI_COLORS["text"], anchor="w", justify="left", height=48,
        ).grid(row=0, column=0, sticky="ew", pady=(2, 0))
        CTkLabel(
            self.form_frame, text="သင့် account ဖြင့် စနစ်ထဲသို့ ဝင်ပါ။",
            text_color=UI_COLORS["muted"], anchor="w", font=(UI_FONT_FAMILY, 11),
        ).grid(row=1, column=0, sticky="ew", pady=(2, 14))

        username_entry = self._field(2, "Username", "Username ရိုက်ထည့်ပါ")
        password_entry = self._field(4, "Password", "Password ရိုက်ထည့်ပါ", show="●")
        if preset_username:
            username_entry.insert(0, preset_username)
        message = self._message_label(6)
        login_button = CTkButton(
            self.form_frame, text="Login ဝင်မည်", height=46,
            fg_color=UI_COLORS["primary"], hover_color=UI_COLORS["primary_hover"],
            font=(UI_FONT_FAMILY, 13, "bold"),
            command=lambda: self._login(username_entry, password_entry, message),
        )
        login_button.grid(row=7, column=0, sticky="ew", pady=(18, 4))
        password_entry.bind(
            "<Return>",
            lambda _event: (self._login(username_entry, password_entry, message), "break")[1],
        )
        self._bind_tab_order([username_entry, password_entry, login_button, self.signup_tab_button])
        self.login_username_entry = username_entry
        self.after(120, password_entry.focus_set if preset_username else username_entry.focus_set)

    def _show_signup(self):
        self._clear_form()
        self.login_tab_button.configure(fg_color="transparent")
        self.signup_tab_button.configure(fg_color=UI_COLORS["primary"])

        CTkLabel(
            self.form_frame, text="Account အသစ်ဖန်တီးရန်", font=(UI_FONT_FAMILY, 23, "bold"),
            text_color=UI_COLORS["text"], anchor="w", justify="left", height=48,
            wraplength=max(300, int(self.window_width * 0.31)),
        ).grid(row=0, column=0, sticky="ew", pady=(2, 0))
        CTkLabel(
            self.form_frame, text="Signup account ကို User role ဖြင့် ဖန်တီးပါမည်။",
            text_color=UI_COLORS["muted"], anchor="w", font=(UI_FONT_FAMILY, 11),
            wraplength=max(300, int(self.window_width * 0.31)), justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(2, 10))

        username_entry = self._field(2, "Username", "Username အသစ်")
        password_entry = self._field(4, "Password", "အနည်းဆုံး ၆ လုံး", show="●")
        confirm_entry = self._field(6, "Confirm Password", "Password ကို ထပ်ရိုက်ပါ", show="●")
        message = self._message_label(8)
        signup_button = CTkButton(
            self.form_frame, text="Account ဖန်တီးမည်", height=46,
            fg_color=UI_COLORS["primary"], hover_color=UI_COLORS["primary_hover"],
            font=(UI_FONT_FAMILY, 13, "bold"),
            command=lambda: self._signup(username_entry, password_entry, confirm_entry, message),
        )
        signup_button.grid(row=9, column=0, sticky="ew", pady=(14, 4))
        confirm_entry.bind(
            "<Return>",
            lambda _event: (self._signup(username_entry, password_entry, confirm_entry, message), "break")[1],
        )
        self._bind_tab_order([username_entry, password_entry, confirm_entry, signup_button, self.login_tab_button])
        self.after(120, username_entry.focus_set)

    def _login(self, username_entry: CTkEntry, password_entry: CTkEntry, message: CTkLabel):
        username = username_entry.get().strip()
        password = password_entry.get()
        if not username or not password:
            message.configure(text="Username နှင့် Password နှစ်ခုလုံး ဖြည့်ပါ။", text_color="#FCA5A5")
            return
        account = self.account_manager.authenticate(username, password)
        if not account:
            message.configure(text="Username သို့မဟုတ် Password မမှန်ပါ။", text_color="#FCA5A5")
            password_entry.delete(0, "end")
            password_entry.focus_set()
            self.audit_logger.log("login_failed", username, "Invalid credentials")
            return

        self.audit_logger.log("login_success", account["username"], f"Role: {account['role']}")
        self.authenticated_account = account
        # End this root and its event loop before creating the dashboard root.
        # Running two CTk roots in one event loop can leave the second window hidden.
        self.destroy()

    def _signup(
        self,
        username_entry: CTkEntry,
        password_entry: CTkEntry,
        confirm_entry: CTkEntry,
        message: CTkLabel,
    ):
        username = username_entry.get().strip()
        password = password_entry.get()
        confirmation = confirm_entry.get()
        if not username or not password or not confirmation:
            message.configure(text="အချက်အလက်အားလုံး ဖြည့်ပါ။", text_color="#FCA5A5")
            return
        if password != confirmation:
            message.configure(text="Password နှစ်ခု မတူပါ။", text_color="#FCA5A5")
            confirm_entry.delete(0, "end")
            confirm_entry.focus_set()
            return
        try:
            self.account_manager.create_account(username, password, "User")
        except ValueError as exc:
            message.configure(text=str(exc), text_color="#FCA5A5")
            return
        self.audit_logger.log("signup", username, "Role: User")
        self._show_login(username)
        if self.login_username_entry is not None:
            self.login_username_entry.focus_set()

    @staticmethod
    def _bind_tab_order(widgets: List[Any]):
        def focus_target(target):
            def handler(_event):
                target.focus_set()
                return "break"
            return handler

        for index, widget in enumerate(widgets):
            widget.bind("<Tab>", focus_target(widgets[(index + 1) % len(widgets)]))
            widget.bind("<Shift-Tab>", focus_target(widgets[(index - 1) % len(widgets)]))
            if isinstance(widget, CTkButton):
                widget.bind("<Return>", lambda _event, button=widget: (button.invoke(), "break")[1])
                widget.bind("<space>", lambda _event, button=widget: (button.invoke(), "break")[1])

def run_application():
    while True:
        login_app = LoginApp()
        login_app.mainloop()
        account = login_app.authenticated_account
        if not account:
            break
        dashboard = VotingApp(account["username"], account["role"])
        dashboard.mainloop()
        if not dashboard.logout_requested:
            break


if __name__ == "__main__":
    run_application()
