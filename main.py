import json
import pickle
import re
import unicodedata
import shutil
import subprocess
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import pandas as pd
from customtkinter import CTk, CTkButton, CTkEntry, CTkFrame, CTkLabel, CTkOptionMenu, CTkScrollableFrame, CTkTextbox, CTkToplevel, set_appearance_mode, set_default_color_theme
from PIL import Image, ImageTk
from sklearn.cluster import KMeans
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "ဆန္ဒမဲပေးခြင်း ပြီးစီးမှု အခြေအနေ စိစစ်ခြင်း"
WINDOW_TITLE = "မဲစာရင်း စိစစ်ရေးစနစ်"
UI_FONT_FAMILY = "Myanmar Text"
PROJECT_ROOT = Path(__file__).resolve().parent
DATASET_PATH = PROJECT_ROOT / "vp-150.csv"
MODEL_PATH = PROJECT_ROOT / "voter_model.pkl"
ACCOUNTS_PATH = PROJECT_ROOT / "accounts.json"
LOG_PATH = PROJECT_ROOT / "audit_logs.json"
ICON_PATH = PROJECT_ROOT / "ECU.ico"
LOGIN_LOGO_PATH = PROJECT_ROOT / "ECU.png"

UI_COLORS = {
    "background": "#0B1120",
    "surface": "#111827",
    "surface_alt": "#172033",
    "border": "#2A3750",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "text": "#F8FAFC",
    "muted": "#94A3B8",
    "success": "#16A34A",
    "field_title": "#60A5FA",
    "field_data": "#F8FAFC",
    "status_complete": "#22C55E",
    "status_pending": "#F59E0B",
    "status_danger": "#EF4444",
}


def fit_window_to_screen(
    window: Any,
    preferred_width: int,
    preferred_height: int,
    minimum_width: int,
    minimum_height: int,
    horizontal_margin: int = 50,
    vertical_margin: int = 90,
) -> tuple[int, int]:
    """Size and center a window without extending beyond the visible screen."""
    screen_width = max(800, int(window.winfo_screenwidth()))
    screen_height = max(600, int(window.winfo_screenheight()))
    available_width = max(760, screen_width - horizontal_margin)
    available_height = max(560, screen_height - vertical_margin)
    effective_min_width = min(minimum_width, available_width)
    effective_min_height = min(minimum_height, available_height)
    width = max(effective_min_width, min(preferred_width, available_width))
    height = max(effective_min_height, min(preferred_height, available_height))
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.minsize(effective_min_width, effective_min_height)
    return width, height


def start_fade_in(window: Any, steps: int = 12, interval_ms: int = 18):
    """Apply a short, subtle window fade when supported by the platform."""
    try:
        window.attributes("-alpha", 0.0)
    except Exception:
        return

    def animate(step: int = 0):
        try:
            window.attributes("-alpha", min(1.0, (step + 1) / steps))
            if step + 1 < steps:
                window.after(interval_ms, lambda: animate(step + 1))
        except Exception:
            return

    window.after(interval_ms, animate)


def apply_window_icon(window: Any):
    """Apply the ECU icon now and again after CTk finishes window setup."""
    if not ICON_PATH.exists():
        return

    def set_icon():
        try:
            window.iconbitmap(str(ICON_PATH))
        except Exception:
            try:
                icon_image = ImageTk.PhotoImage(Image.open(ICON_PATH))
                window._ecu_window_icon = icon_image
                window.iconphoto(True, icon_image)
            except Exception:
                return

    set_icon()
    try:
        window.after(250, set_icon)
    except Exception:
        pass

BURMESE_DIGITS = {
    "၀": "0", "၁": "1", "၂": "2", "၃": "3", "၄": "4",
    "၅": "5", "၆": "6", "၇": "7", "၈": "8", "၉": "9",
}


def burmese_display(value: Any) -> str:
    return str(value).translate(str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉"))


def canonical_field(value: Any) -> str:
    return re.sub(r"\s+", "", normalize_text(value))


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    for src, dst in BURMESE_DIGITS.items():
        text = text.replace(src, dst)
    text = text.replace("၊", " ").replace("-", " ")
    text = re.sub(r"[^A-Za-z0-9\u1000-\u109F\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def transliterate_burmese_to_latin(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    replacements = {
        "ဦး": "u ", "ဦ": "u ", "ဥ": "u ", "ဍ": "d", "န": "n", "လ": "l", "တ": "t",
        "မ": "m", "က": "k", "စ": "s", "အ": "a", "ယ": "y", "ြ": "w", "ော": "o", "ို": "o",
        "င်": "ing", "င်း": "ing", "ည်": "i", "ား": "a", "စ်": "it", "သ": "th", "ဖြ": "ph",
        "ိ": "i", "ီ": "i", "ု": "u", "ူ": "u", "ေ": "e", "်": "", "့": "", "း": "",
        "့": "", "္": "", "်": "",
    }
    result = text
    for src, dst in replacements.items():
        result = result.replace(src, dst)
    result = re.sub(r"\s+", " ", result).strip()
    return result


def safe_get(row: pd.Series, *keys: str) -> Any:
    for key in keys:
        if key in row.index:
            return row[key]
    return ""


class AccountManager:
    SUPER_ADMIN_USERNAME = "Super Admin"
    SUPER_ADMIN_PASSWORD = "199199"

    def __init__(self, path: Path):
        self.path = path
        self.accounts = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        data: Dict[str, Dict[str, Any]] = {}
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                try:
                    loaded = json.load(fh)
                    data = loaded if isinstance(loaded, dict) else {}
                except json.JSONDecodeError:
                    data = {}

        # Remove only the application's obsolete built-in credential. User-created
        # accounts are preserved, including existing Super Admin accounts.
        legacy = data.get("superadmin", {})
        if legacy.get("username") == "superadmin" and legacy.get("password") == "admin123":
            data.pop("superadmin", None)
        data[self.SUPER_ADMIN_USERNAME] = {
            "username": self.SUPER_ADMIN_USERNAME,
            "password": self.SUPER_ADMIN_PASSWORD,
            "role": "Super Admin",
            "approved": True,
            "created_at": data.get(self.SUPER_ADMIN_USERNAME, {}).get(
                "created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ),
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def save(self):
        self.path.write_text(json.dumps(self.accounts, ensure_ascii=False, indent=2), encoding="utf-8")

    def create_account(self, username: str, password: str, role: str):
        key = username.strip()
        if not key:
            raise ValueError("Username must not be empty.")
        if len(password) < 6:
            raise ValueError("Password must contain at least 6 characters.")
        if any(item.get("username", "").casefold() == key.casefold() for item in self.accounts.values()):
            raise ValueError("This username already exists.")
        self.accounts[key] = {
            "username": key,
            "password": password,
            "role": role,
            "approved": True,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.save()

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        login_name = username.strip().casefold()
        for account in self.accounts.values():
            if account.get("username", "").strip().casefold() != login_name:
                continue
            if account.get("password") != password or not account.get("approved", False):
                return None
            return account.copy()
        return None

    def list_accounts(self):
        return list(self.accounts.values())


class AuditLogger:
    def __init__(self, path: Path):
        self.path = path
        self.logs = self._load()

    def _load(self):
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")
        with self.path.open("r", encoding="utf-8") as fh:
            try:
                return json.load(fh)
            except json.JSONDecodeError:
                return []

    def log(self, action: str, username: str, details: str = ""):
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": username,
            "action": action,
            "details": details,
        }
        self.logs.append(entry)
        self.path.write_text(json.dumps(self.logs, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_logs(self):
        return self.logs


class VotingDataset:
    def __init__(self, base_path: Path):
        self.base_path = base_path

    def rename_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        mappings = {
            "အမည်": "name",
            "name": "name",
            "ကျား/မ": "gender",
            "မွေးသက္ကရာဇ်": "date_of_birth",
            "နိုင်ငံသားစိစစ်ရေးကတ်အမှတ်": "id_number",
            "အဘအမည်": "father_name",
            "အမိအမည်": "mother_name",
            "အမြဲတမ်းနေရပ်လိပ်စာ": "address",
            "မဲစာရင်းအမှတ်": "voter_no",
            "ဆန္ဒမဲပေးမှုအခြေအနေ": "vote_status",
            "လူမျိုး": "ethnicity",
            "ပြစ်မှုမှတ်တမ်း": "criminal_record",
            "Remark": "remark",
            "Sign": "sign",
        }
        renamed = df.copy()
        renamed.columns = [mappings.get(str(col).strip(), str(col).strip()) for col in renamed.columns]
        return renamed

    def load(self, path: Optional[Path] = None) -> pd.DataFrame:
        source = path or DATASET_PATH
        if not source.exists():
            raise FileNotFoundError(f"Dataset not found: {source}")
        df = (pd.read_excel(source, dtype=str) if source.suffix.lower() in {".xlsx", ".xls"}
              else pd.read_csv(source, encoding="utf-8-sig", dtype=str)).fillna("")
        return self.rename_columns(df)

    def build_training_features(self, df: pd.DataFrame) -> pd.DataFrame:
        work = df.copy()
        for col in ["name", "father_name", "id_number", "gender", "ethnicity", "vote_status", "criminal_record"]:
            if col not in work.columns:
                work[col] = ""
        work["name"] = work["name"].fillna("").astype(str)
        work["father_name"] = work["father_name"].fillna("").astype(str)
        work["id_number"] = work["id_number"].fillna("").astype(str)
        work["gender"] = work["gender"].fillna("").astype(str)
        work["ethnicity"] = work["ethnicity"].fillna("").astype(str)
        work["criminal_record"] = work["criminal_record"].fillna("").astype(str)
        work["vote_status"] = work["vote_status"].fillna("").astype(str)

        work["name_length"] = work["name"].str.len()
        work["father_name_length"] = work["father_name"].str.len()
        work["id_last_6"] = work["id_number"].apply(
            lambda x: int("".join(re.findall(r"\d", normalize_text(x)))[-6:]) if re.search(r"\d", normalize_text(x)) else 0
        )
        work["has_father_name"] = work["father_name"].apply(lambda x: 1 if str(x).strip() else 0)
        work["is_male"] = work["gender"].apply(lambda x: 1 if "ကျား" in str(x) or "male" in str(x).lower() else 0)
        work["has_criminal_record"] = work["criminal_record"].apply(lambda x: 1 if "ရှိ" in str(x) or "yes" in str(x).lower() or "true" in str(x).lower() else 0)
        work["vote_target"] = work["vote_status"].apply(lambda value: 1 if normalize_text(value) in {"ပြီး", "voted", "yes", "1"} else 0)
        return work


class ModelManager:
    def __init__(self, model_path: Path):
        self.model_path = model_path

    def train_and_save(self, dataset: pd.DataFrame) -> Dict[str, Any]:
        if "vote_status" not in dataset.columns and any("ဆန္ဒမဲ" in str(col) for col in dataset.columns):
            dataset = VotingDataset(PROJECT_ROOT).rename_columns(dataset)
        feature_frame = VotingDataset(PROJECT_ROOT).build_training_features(dataset)

        feature_cols = ["name_length", "father_name_length", "id_last_6", "has_father_name", "is_male", "has_criminal_record"]
        categorical_cols = ["gender", "ethnicity"]

        X = feature_frame[feature_cols + categorical_cols]
        y = feature_frame["vote_target"]

        numeric_transformer = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ])
        categorical_transformer = Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ])

        preprocessor = ColumnTransformer([
            ("num", numeric_transformer, feature_cols),
            ("cat", categorical_transformer, categorical_cols),
        ])

        clf = LogisticRegression(max_iter=2000, solver="lbfgs")
        pipeline = Pipeline([("preprocessor", preprocessor), ("classifier", clf)])
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
        pipeline.fit(X_train, y_train)

        kmeans = KMeans(n_clusters=min(3, max(1, len(feature_frame) // 5)), random_state=42)
        kmeans.fit(feature_frame[feature_cols].fillna(0))

        artifact = {
            "model": pipeline,
            "kmeans": kmeans,
            "feature_cols": feature_cols,
            "categorical_cols": categorical_cols,
            "source_rows": len(feature_frame),
            "training_accuracy": float(pipeline.score(X_test, y_test)),
        }
        with open(self.model_path, "wb") as fh:
            pickle.dump(artifact, fh)
        return artifact

    def load_model(self):
        if not self.model_path.exists():
            raise FileNotFoundError("No trained model exists. Please train a model first.")
        with open(self.model_path, "rb") as fh:
            return pickle.load(fh)

    def predict_vote_status(self, row: Dict[str, Any]) -> Dict[str, Any]:
        artifact = self.load_model()
        model = artifact["model"]
        frame = pd.DataFrame([row])
        for col in artifact["feature_cols"]:
            if col not in frame.columns:
                frame[col] = 0
        for col in artifact["categorical_cols"]:
            if col not in frame.columns:
                frame[col] = ""
        features = frame[artifact["feature_cols"] + artifact["categorical_cols"]]
        pred = model.predict(features)[0]
        proba = model.predict_proba(features)[0]
        label = "ပြီး" if pred == 1 else "မပြီး"
        return {"label": label, "confidence": float(np.max(proba))}


class OCRProcessor:
    def __init__(self):
        self.reader = None
        self.tesseract = shutil.which("tesseract")
        if not self.tesseract:
            installed = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            if installed.exists():
                self.tesseract = str(installed)
        self.last_error = ""
        self.ocr_language = "mya"
        if self.tesseract:
            try:
                language_result = subprocess.run(
                    [self.tesseract, "--list-langs"],
                    capture_output=True, encoding="utf-8", errors="replace", timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                languages = set(language_result.stdout.split())
                if "mya" in languages and "eng" in languages:
                    self.ocr_language = "mya+eng"
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _preprocess_for_ocr(self, image):
        if image is None:
            return None
        image = cv2.resize(image, (image.shape[1] * 2, image.shape[0] * 2))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 5, 75, 75)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    @staticmethod
    def _has_meaningful_text(value: str) -> bool:
        if not value:
            return False
        plain = re.sub(r"[^A-Za-z0-9\u1000-\u109F\s/()\-]", "", value)
        return bool(plain.strip()) and bool(re.search(r"[A-Za-z0-9\u1000-\u109F]", plain))

    @staticmethod
    def _parse_structured_fields(raw_ocr_text: str) -> Dict[str, str]:
        text = unicodedata.normalize("NFKC", raw_ocr_text or "")
        fields = {"name": "", "father_name": "", "id_number": ""}
        # Stop each value at a new line or the next field label.
        labels = r"ဖခင်အမည်|အဘအမည်|ဖခင်|အဘ|အမည်|father(?:['’]s)?(?:\s+name)?|name|နိုင်ငံသားစိစစ်ရေးကတ်(?:ပြား)?အမှတ်|မှတ်ပုံတင်(?:အမှတ်)?|NRC(?:\s*(?:No\.?|Number))?|ID"
        pattern = re.compile(r"(?P<label>" + labels + r")\s*[:?\-]?\s*(?P<value>.*?)(?=\r?\n|(?:" + labels + r")\s*[:?]?|$)", re.IGNORECASE)
        for match in pattern.finditer(text):
            label = match.group("label").lower()
            value = re.sub(r"\s+", " ", match.group("value")).strip(" :?-.၊\t")
            if any(word in label for word in ("father", "ဖခင်", "အဘ")):
                if OCRProcessor._looks_like_person_name(value):
                    fields["father_name"] = value
            elif label in {"name", "အမည်"}:
                if OCRProcessor._looks_like_person_name(value):
                    fields["name"] = value
        id_match = re.search(
            r"[0-9၀-၉]{1,2}\s*/\s*[A-Za-z\u1000-\u109f]{2,}\s*"
            r"[(（]?\s*(?:နိုင်|နိုင|N|NAING)\s*[)）]?\s*[0-9၀-၉]{6}(?![0-9၀-၉])",
            text, flags=re.IGNORECASE,
        )
        if id_match:
            fields["id_number"] = re.sub(r"\s+", "", id_match.group())
        return {key: value for key, value in fields.items() if value}

    @staticmethod
    def _looks_like_person_name(value: str) -> bool:
        value = re.sub(r"\s+", " ", str(value)).strip()
        if len(value) < 3 or len(value) > 60:
            return False
        letters = re.findall(r"[A-Za-z\u1000-\u109F]", value)
        digits = re.findall(r"[0-9၀-၉]", value)
        return len(letters) >= 3 and len(digits) <= 1

    @staticmethod
    def _ocr_quality(text: str) -> int:
        fields = OCRProcessor._parse_structured_fields(text)
        score = len(fields) * 100
        score += sum(20 for label in ("အမည်", "ဖခင်", "အဘ", "မှတ်", "NRC", "Name") if label.lower() in text.lower())
        score += min(len(re.findall(r"[A-Za-z0-9\u1000-\u109F]", text)), 100)
        return score

    def _run_tesseract(self, source: Any, psm: int) -> str:
        command = [self.tesseract, "stdin" if isinstance(source, bytes) else str(source), "stdout",
                   "-l", self.ocr_language, "--psm", str(psm)]
        result = subprocess.run(
            command, input=source if isinstance(source, bytes) else None,
            capture_output=True, encoding=None if isinstance(source, bytes) else "utf-8",
            errors=None if isinstance(source, bytes) else "replace", timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = result.stdout.decode("utf-8", "replace") if isinstance(result.stdout, bytes) else result.stdout
        return output.strip()

    def extract_card(self, image_path: str) -> Dict[str, Any]:
        self.last_error = ""
        if not self.tesseract:
            self.last_error = "မြန်မာစာ OCR အတွက် Tesseract နှင့် mya language data ထည့်သွင်းရန်လိုပါသည်။"
            return {"raw_text": "", "fields": {}}
        try:
            image = cv2.imread(str(image_path))
            if image is None:
                self.last_error = "ပုံဖိုင်ကို ဖွင့်မရပါ။"
                return {"raw_text": "", "fields": {}}

            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
            threshold = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            encoded_ok, encoded = cv2.imencode(".png", threshold)

            candidates = [self._run_tesseract(image_path, 6), self._run_tesseract(image_path, 11)]
            if encoded_ok:
                candidates.append(self._run_tesseract(encoded.tobytes(), 6))
            candidates = [text for text in candidates if text]
            candidates.sort(key=self._ocr_quality, reverse=True)

            merged_fields: Dict[str, str] = {}
            for candidate in candidates:
                for key, value in self._parse_structured_fields(candidate).items():
                    merged_fields.setdefault(key, value)
            return {"raw_text": candidates[0] if candidates else "", "fields": merged_fields}
        except (OSError, subprocess.TimeoutExpired, cv2.error):
            self.last_error = "OCR ဖတ်မရပါ။ ပြန်စမ်းပါ။"
            return {"raw_text": "", "fields": {}}

    def extract_text(self, image_path: str) -> str:
        return self.extract_card(image_path)["raw_text"]

    def extract_candidate_queries(self, raw_ocr_text: str) -> List[str]:
        text = raw_ocr_text or ""
        queries: List[str] = []
        if not text:
            return queries

        cleaned = re.sub(r"\s+", " ", text).strip()
        fields = self._parse_structured_fields(cleaned)

        if fields.get("name"):
            queries.append(fields["name"])
        if fields.get("father_name"):
            queries.append(fields["father_name"])
        if fields.get("id_number"):
            queries.append(fields["id_number"])
            digits = re.findall(r"\d+", fields["id_number"])
            if digits:
                queries.append(digits[-1])

        for value in [fields.get("name"), fields.get("father_name"), fields.get("id_number")]:
            if value and value not in queries:
                queries.append(value)

        if fields.get("name") and fields.get("father_name"):
            queries.append(f"{fields['name']} {fields['father_name']}")
        if fields.get("name") and fields.get("id_number"):
            queries.append(f"{fields['name']} {fields['id_number']}")
        if fields.get("father_name") and fields.get("id_number"):
            queries.append(f"{fields['father_name']} {fields['id_number']}")

        if cleaned and self._has_meaningful_text(cleaned):
            queries.append(cleaned)

        name_match = re.search(r"(?:Name|Name\s*:|အမည်|Name\s+)?([A-Za-z\u1000-\u109F][A-Za-z\u1000-\u109F\-\' ]{2,40})", cleaned, flags=re.IGNORECASE)
        if name_match:
            name = re.sub(r"\s+", " ", name_match.group(1)).strip()
            if name and name not in queries:
                queries.append(name)

        for line in cleaned.split("\n"):
            stripped = line.strip()
            if len(stripped) > 4:
                if self._has_meaningful_text(stripped):
                    queries.append(stripped)

        deduped = []
        seen = set()
        for q in queries:
            q = q.strip()
            if q and q not in seen:
                seen.add(q)
                deduped.append(q)
        return deduped[:20]


class VoterQueryEngine:
    def __init__(self, dataset: pd.DataFrame, model_manager: ModelManager):
        self.dataset = dataset
        self.model_manager = model_manager

    def extract_matches(self, query: str) -> List[Dict[str, Any]]:
        search = normalize_text(query)
        if not search:
            return []
        search_roman = transliterate_burmese_to_latin(search)
        search_digits = "".join(re.findall(r"\d", search))
        records: List[Dict[str, Any]] = []
        for idx, row in self.dataset.iterrows():
            name = normalize_text(safe_get(row, "name", "အမည်"))
            father = normalize_text(safe_get(row, "father_name", "အဘအမည်"))
            name_roman = transliterate_burmese_to_latin(name)
            father_roman = transliterate_burmese_to_latin(father)
            id_number = normalize_text(safe_get(row, "id_number", "နိုင်ငံသားစိစစ်ရေးကတ်အမှတ်"))
            id_digits = "".join(re.findall(r"\d", id_number))
            records.append({
                "row_index": idx,
                "name": str(safe_get(row, "name", "အမည်")),
                "father_name": str(safe_get(row, "father_name", "အဘအမည်")),
                "id_number": str(safe_get(row, "id_number", "နိုင်ငံသားစိစစ်ရေးကတ်အမှတ်")),
                "voter_no": str(safe_get(row, "voter_no", "မဲစာရင်းအမှတ်")),
                "vote_status": str(safe_get(row, "vote_status", "ဆန္ဒမဲပေးမှုအခြေအနေ")),
                "_name": name,
                "_father": father,
                "_name_roman": name_roman,
                "_father_roman": father_roman,
                "_id": id_number,
                "_id_digits": id_digits,
            })

        def finish(items: List[Dict[str, Any]], reason: str, score: int) -> List[Dict[str, Any]]:
            output = []
            for item in items[:10]:
                visible = {key: value for key, value in item.items() if not key.startswith("_")}
                visible["match_reason"] = reason
                visible["match_score"] = score
                output.append(visible)
            return output

        # NRC searches never mix with name or father-name results.
        if len(search_digits) >= 6:
            exact_id = [item for item in records if search == item["_id"]]
            if exact_id:
                return finish(exact_id, "id_exact", 100)
            id_tail = search_digits[-6:]
            tail_matches = [item for item in records if item["_id_digits"][-6:] == id_tail]
            return finish(tail_matches, "id_last_six", 95)

        exact_names = [item for item in records if item["_name"] == search]
        if exact_names:
            return finish(exact_names, "name_exact", 100)

        if len(search) >= 3:
            partial_names = [item for item in records if search in item["_name"]]
            if partial_names:
                return finish(partial_names, "name_partial", 90)

        if len(search_roman) >= 4:
            roman_names = [item for item in records if item["_name_roman"] == search_roman]
            if roman_names:
                return finish(roman_names, "name_roman", 88)

        exact_fathers = [item for item in records if item["_father"] == search]
        if exact_fathers:
            return finish(exact_fathers, "father_exact", 85)

        if len(search) >= 3:
            partial_fathers = [item for item in records if search in item["_father"]]
            if partial_fathers:
                return finish(partial_fathers, "father_partial", 80)

        fuzzy_names = []
        for item in records:
            ratio = SequenceMatcher(None, item["_name"], search).ratio()
            roman_ratio = SequenceMatcher(None, item["_name_roman"], search_roman).ratio() if search_roman else 0.0
            best_ratio = max(ratio, roman_ratio)
            if best_ratio >= 0.88:
                fuzzy_names.append((best_ratio, item))
        if fuzzy_names:
            fuzzy_names.sort(key=lambda pair: pair[0], reverse=True)
            best = fuzzy_names[0][0]
            close_matches = [item for ratio, item in fuzzy_names if ratio >= best - 0.02]
            return finish(close_matches, "name_fuzzy", int(best * 100))
        return []

    def extract_id_tail_matches(self, query: str) -> List[Dict[str, Any]]:
        """Match a numeric-only query against exactly the last six NRC digits."""
        normalized_query = normalize_text(query)
        query_digits = "".join(re.findall(r"\d", normalized_query))
        if len(query_digits) != 6:
            return []

        matches: List[Dict[str, Any]] = []
        for idx, row in self.dataset.iterrows():
            id_number = str(safe_get(row, "id_number", "နိုင်ငံသားစိစစ်ရေးကတ်အမှတ်"))
            normalized_id = normalize_text(id_number)
            id_digits = "".join(re.findall(r"\d", normalized_id))
            if len(id_digits) < 6 or id_digits[-6:] != query_digits:
                continue
            matches.append({
                "row_index": idx,
                "name": str(safe_get(row, "name", "အမည်")),
                "father_name": str(safe_get(row, "father_name", "အဘအမည်")),
                "id_number": id_number,
                "voter_no": str(safe_get(row, "voter_no", "မဲစာရင်းအမှတ်")),
                "vote_status": str(safe_get(row, "vote_status", "ဆန္ဒမဲပေးမှုအခြေအနေ")),
                "match_reason": "id_last_six",
                "match_score": 100,
            })
        return matches[:10]

    def evaluate_id_last_six(self, query: str, role: str = "User") -> Dict[str, Any]:
        matches = self.extract_id_tail_matches(query)
        if not matches:
            return {
                "status": "no_match",
                "message": "မှတ်ပုံတင်နောက်ဆုံးဂဏန်း ၆ လုံးနှင့် ကိုက်ညီသောအချက်အလက် မတွေ့ရှိပါ။",
            }
        if len(matches) > 1:
            return {
                "status": "multiple_matches",
                "matches": matches,
                "message": "မှတ်ပုံတင်နောက်ဆုံးဂဏန်း ၆ လုံးတူသော မှတ်တမ်းများရှိပါသည်။",
            }
        match = matches[0]
        row = self.dataset.loc[match["row_index"]]
        return {
            "status": "match",
            "candidate": row.to_dict(),
            "reply": self.format_candidate(row, role),
        }

    @staticmethod
    def format_candidate(row: pd.Series, role: str) -> str:
        user_fields = (
            ("အမည်", "name"),
            ("အဘအမည်", "father_name"),
            ("မှတ်ပုံတင်အမှတ်", "id_number"),
            ("မဲပေးမှုအခြေအနေ", "vote_status"),
            ("မဲစာရင်းအမှတ်", "voter_no"),
        )
        admin_fields = (
            ("အမည်", "name"),
            ("ကျား/မ", "gender"),
            ("မွေးသက္ကရာဇ်", "date_of_birth"),
            ("မှတ်ပုံတင်အမှတ်", "id_number"),
            ("အဘအမည်", "father_name"),
            ("အမိအမည်", "mother_name"),
            ("အမြဲတမ်းနေရပ်လိပ်စာ", "address"),
            ("လူမျိုး", "ethnicity"),
            ("မဲစာရင်းအမှတ်", "voter_no"),
            ("မဲပေးမှုအခြေအနေ", "vote_status"),
            ("ပြစ်မှုမှတ်တမ်း", "criminal_record"),
            ("မှတ်ချက်", "remark"),
            ("လက်မှတ်", "sign"),
        )
        fields = admin_fields if role.lower() in {"admin", "super admin"} else user_fields
        lines = [f"{label}: {safe_get(row, key, label)}" for label, key in fields]
        return burmese_display("\n".join(lines))

    def evaluate_card(self, fields: Dict[str, str], role: str = "User") -> Dict[str, Any]:
        labels = {"name": "အမည်", "father_name": "ဖခင်အမည်", "id_number": "မှတ်ပုံတင်အမှတ်"}
        missing = [label for key, label in labels.items() if not fields.get(key)]
        if missing:
            return {"reply": "ဖတ်မရသောအချက်များ: " + "၊ ".join(missing) + "။ ကြည်လင်သောကတ်ပုံကို ပြန်တင်ပါ။"}
        candidates = self.dataset[self.dataset["id_number"].map(canonical_field) == canonical_field(fields["id_number"])]
        if candidates.empty:
            return {"reply": "မှတ်ပုံတင်အမှတ်နှင့် ကိုက်ညီသောမှတ်တမ်း မတွေ့ပါ။"}
        reports = []
        verified = []
        for _, row in candidates.iterrows():
            checks = {key: canonical_field(fields[key]) == canonical_field(row.get(key, "")) for key in labels}
            if all(checks.values()):
                verified.append(row)
            reports.append("\n".join(f"{label}: {fields[key]} — {'ကိုက်ညီ' if checks[key] else 'မကိုက်ညီ'}" for key, label in labels.items()))
        if len(verified) == 1:
            row = verified[0]
            reply = "အချက်သုံးချက်လုံး ကိုက်ညီပါသည်။\n" + self.format_candidate(row, role)
        elif len(verified) > 1:
            reply = "ကိုက်ညီသောမှတ်တမ်း တစ်ခုထက်ပိုရှိနေပါသည်။ datafile ကို စစ်ဆေးပါ။"
        else:
            reply = "အချက်အလက် မကိုက်ညီပါ။\n" + "\n\n".join(reports)
        return {"reply": burmese_display(reply)}

    def evaluate_query(self, raw_query: str, role: str = "User") -> Dict[str, Any]:
        matches = self.extract_matches(raw_query)
        if not matches:
            return {"status": "no_match", "message": "မည်သည့်အချက်အလက်ကိုမှ တူညီမှုမတွေ့ရှိပါ။"}

        if len(matches) > 1:
            return {"status": "multiple_matches", "matches": matches, "message": "အချက်အလက်များစွာ တူညီမှုရှိသည်။"}

        match = matches[0]
        row = self.dataset.loc[match["row_index"]]
        return {
            "status": "match",
            "candidate": row.to_dict(),
            "reply": self.format_candidate(row, role),
        }


class VotingApp(CTk):
    def __init__(self, username: str = "Guest", role: str = "User"):
        super().__init__()
        self.title(WINDOW_TITLE)
        apply_window_icon(self)
        set_appearance_mode("dark")
        set_default_color_theme("blue")
        self.configure(fg_color=UI_COLORS["background"])
        self.window_width, self.window_height = fit_window_to_screen(
            self, 1500, 900, 1080, 680, horizontal_margin=40, vertical_margin=80
        )

        self.account_manager = AccountManager(ACCOUNTS_PATH)
        self.audit_logger = AuditLogger(LOG_PATH)
        self.dataset_manager = VotingDataset(PROJECT_ROOT)
        self.model_manager = ModelManager(MODEL_PATH)
        self.current_dataset = self._load_default_dataset()
        self.query_engine = VoterQueryEngine(self.current_dataset, self.model_manager)
        self.ocr = OCRProcessor()
        self.current_username = username.strip() or "Guest"
        self.role_var = role if role in {"User", "Admin", "Super Admin"} else "User"
        self.logout_requested = False

        self._build_ui()
        start_fade_in(self)

    def _load_default_dataset(self) -> pd.DataFrame:
        try:
            df = self.dataset_manager.load(DATASET_PATH)
            if not df.empty:
                return df
        except Exception:
            pass
        return pd.DataFrame([
            {
                "name": "Example Voter",
                "gender": "ကျား",
                "date_of_birth": "1995-01-01",
                "id_number": "12/ABC123456",
                "father_name": "U Aye",
                "mother_name": "Daw Mya",
                "ethnicity": "ဗမာ",
                "voter_no": "1234",
                "vote_status": "မပြီး",
                "criminal_record": "မရှိ",
                "remark": "-",
                "sign": "-",
            }
        ])

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.container = CTkFrame(self, corner_radius=0, fg_color=UI_COLORS["background"])
        self.container.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)
        self.container.grid_columnconfigure(1, weight=1)
        self.container.grid_rowconfigure(1, weight=1)

        self.header = CTkFrame(
            self.container, fg_color=UI_COLORS["surface"],
            border_width=1, border_color=UI_COLORS["border"], corner_radius=14,
        )
        self.header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=0, pady=(0, 12))
        self.header.grid_columnconfigure(0, weight=1)

        self.title_label = CTkLabel(
            self.header, text=APP_TITLE, font=(UI_FONT_FAMILY, 25, "bold"),
            text_color=UI_COLORS["text"], anchor="w", justify="left",
            wraplength=max(440, int(self.window_width * 0.52)),
        )
        self.title_label.grid(row=0, column=0, sticky="sw", padx=(22, 10), pady=(15, 0))
        CTkLabel(
            self.header, text="နိုင်ငံသားအချက်အလက်နှင့် မဲစာရင်း စိစစ်ရေးစနစ်",
            font=(UI_FONT_FAMILY, 12), text_color=UI_COLORS["muted"],
            anchor="w", justify="left", wraplength=max(440, int(self.window_width * 0.52)),
        ).grid(row=1, column=0, sticky="nw", padx=(22, 10), pady=(1, 15))

        role_area = CTkFrame(
            self.header, fg_color=UI_COLORS["surface_alt"], corner_radius=10,
            border_width=1, border_color=UI_COLORS["border"],
        )
        role_area.grid(row=0, column=1, rowspan=2, sticky="e", padx=22, pady=14)
        CTkLabel(
            role_area, text=self.current_username, text_color=UI_COLORS["text"],
            font=(UI_FONT_FAMILY, 13, "bold"), wraplength=190, justify="left",
        ).pack(anchor="w", padx=14, pady=(8, 0))
        CTkLabel(
            role_area, text=self.role_var, text_color="#60A5FA", font=(UI_FONT_FAMILY, 11),
        ).pack(anchor="w", padx=14, pady=(0, 5))
        self.logout_button = CTkButton(
            role_area, text="Logout", width=110, height=30, command=self._logout,
            fg_color="#B91C1C", hover_color="#991B1B", font=(UI_FONT_FAMILY, 11, "bold"),
        )
        self.logout_button.pack(fill="x", padx=10, pady=(0, 9))

        self.sidebar = CTkFrame(
            self.container, width=220, corner_radius=14, fg_color=UI_COLORS["surface"],
            border_width=1, border_color=UI_COLORS["border"],
        )
        self.sidebar.grid(row=1, column=0, sticky="nsew", padx=(0, 12), pady=0)
        self.sidebar.grid_columnconfigure(0, weight=1)
        CTkLabel(
            self.sidebar, text="စနစ်မီနူး", font=(UI_FONT_FAMILY, 15, "bold"),
            text_color=UI_COLORS["text"], anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(20, 12))

        self.chat_tab = CTkFrame(
            self.container, corner_radius=14, fg_color=UI_COLORS["surface"],
            border_width=1, border_color=UI_COLORS["border"],
        )
        self.chat_tab.grid(row=1, column=1, sticky="nsew", padx=(0, 12), pady=0)
        self.chat_tab.grid_columnconfigure(0, weight=1)
        self.chat_tab.grid_rowconfigure(1, weight=1)

        self.info_panel = CTkFrame(
            self.container, width=310, corner_radius=14, fg_color=UI_COLORS["surface"],
            border_width=1, border_color=UI_COLORS["border"],
        )
        self.info_panel.grid(row=1, column=2, sticky="nsew", padx=0, pady=0)
        self.info_panel.grid_columnconfigure(0, weight=1)
        self.info_panel.grid_rowconfigure(2, weight=1)

        self.sidebar_buttons = []
        navigation = [("စိစစ်မေးမြန်းရန်", self._focus_chat)]
        if self.role_var in {"Admin", "Super Admin"}:
            navigation.extend([
                ("Model လေ့ကျင့်ရန်", self._train_model),
                ("Datafile စီမံရန်", self._open_dataset_panel),
                ("လုပ်ဆောင်မှုမှတ်တမ်း", self._open_logs_panel),
            ])
        if self.role_var == "Super Admin":
            navigation.append(("Account များ", self._open_accounts_panel))
        for i, text in enumerate(navigation, start=1):
            label, command = text
            btn = CTkButton(
                self.sidebar, text=label, command=command, anchor="w", height=42,
                fg_color=UI_COLORS["surface_alt"], hover_color=UI_COLORS["primary_hover"],
                border_width=1, border_color=UI_COLORS["border"],
                font=(UI_FONT_FAMILY, 12),
            )
            btn.grid(row=i, column=0, sticky="ew", padx=12, pady=6)
            self.sidebar_buttons.append(btn)

        title_area = CTkFrame(self.chat_tab, fg_color="transparent")
        title_area.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        self.chat_title = CTkLabel(
            title_area, text="မဲစာရင်း အချက်အလက်စိစစ်ရန်",
            font=(UI_FONT_FAMILY, 20, "bold"), text_color=UI_COLORS["text"],
            anchor="w", justify="left",
        )
        self.chat_title.pack(anchor="w")
        CTkLabel(
            title_area,
            text="အမည်၊ အဘအမည် သို့မဟုတ် NRC နောက်ဆုံး ၆ လုံး (၀၉၈၄၃၆ / 098436) ဖြင့် ရှာနိုင်ပါသည်",
            font=(UI_FONT_FAMILY, 11), text_color=UI_COLORS["muted"],
            anchor="w", justify="left", wraplength=max(360, int(self.window_width * 0.42)),
        ).pack(anchor="w", pady=(2, 0))

        self.message_box = CTkTextbox(
            self.chat_tab, height=400, wrap="word", font=(UI_FONT_FAMILY, 14),
            fg_color=UI_COLORS["background"], border_width=1, border_color=UI_COLORS["border"],
        )
        self.message_box.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
        self._message_queue: List[List[str]] = []
        self._typing_active = False
        self._typing_delay_ms = 14
        self._danger_bar_counter = 0
        self._configure_message_tags()
        self.message_box.insert(
            "end",
            "မဲဆန္ဒရှင်အမည်၊ မှတ်ပုံတင်အမှတ် သို့မဟုတ် အဘအမည်ကို ရိုက်ထည့်ပြီး စစ်ဆေးနိုင်ပါသည်။\n",
            "field_data",
        )
        self.message_box.configure(state="disabled")

        self.choice_frame = None
        self.choice_buttons: List[CTkButton] = []
        self.choice_matches: List[Dict[str, Any]] = []
        self.choice_index = 0

        self.control_bar = CTkFrame(self.chat_tab, fg_color="transparent")
        self.control_bar.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 18))
        self.control_bar.grid_columnconfigure(0, weight=1)

        self.input_entry = CTkEntry(
            self.control_bar, placeholder_text="အမည် / အဘအမည် / ၀၉၈၄၃၆ / 098436...", height=46,
            fg_color=UI_COLORS["surface_alt"], border_color=UI_COLORS["border"],
            font=(UI_FONT_FAMILY, 13),
        )
        self.input_entry.grid(row=0, column=0, sticky="ew")
        self.plus_button = CTkButton(
            self.control_bar, text="＋", width=50, height=46, command=self._show_attachment_menu,
            font=(UI_FONT_FAMILY, 18, "bold"), fg_color=UI_COLORS["surface_alt"],
            hover_color=UI_COLORS["primary_hover"], border_width=1, border_color=UI_COLORS["border"],
        )
        self.plus_button.grid(row=0, column=1, padx=(8, 6))
        self.send_button = CTkButton(
            self.control_bar, text="ပို့မည်", command=self._handle_chat_submit, width=110, height=46,
            fg_color=UI_COLORS["primary"], hover_color=UI_COLORS["primary_hover"],
            font=(UI_FONT_FAMILY, 13, "bold"),
        )
        self.send_button.grid(row=0, column=2, padx=(0, 0))
        self.input_entry.bind("<Return>", self._submit_from_enter)

        self.info_title = CTkLabel(
            self.info_panel, text="စနစ်အခြေအနေ", font=(UI_FONT_FAMILY, 18, "bold"),
            text_color=UI_COLORS["text"], anchor="w",
        )
        self.info_title.grid(row=0, column=0, sticky="w", padx=18, pady=(20, 8))

        self.model_stats = CTkTextbox(
            self.info_panel, height=220, wrap="word", font=(UI_FONT_FAMILY, 12),
            fg_color=UI_COLORS["surface_alt"], border_width=1, border_color=UI_COLORS["border"],
        )
        self.model_stats.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
        self.model_stats.configure(state="disabled")

        self.account_panel = CTkScrollableFrame(self.info_panel, corner_radius=12)
        self.account_panel.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 10))
        self.account_panel.grid_columnconfigure(0, weight=1)
        self._render_account_summary()
        self._refresh_model_status()
        self._bind_tab_order(
            [self.input_entry, self.plus_button, self.send_button, self.logout_button] + self.sidebar_buttons
        )
        self.after(150, self.input_entry.focus_set)

    def _logout(self):
        self.audit_logger.log("logout", self.current_username, f"Role: {self.role_var}")
        self.logout_requested = True
        self.destroy()

    def _submit_from_enter(self, _event=None):
        self._handle_chat_submit()
        return "break"

    @staticmethod
    def _bind_tab_order(widgets: List[Any]):
        def focus_target(target):
            def handler(_event):
                target.focus_set()
                return "break"
            return handler

        active = [widget for widget in widgets if widget is not None]
        for index, widget in enumerate(active):
            widget.bind("<Tab>", focus_target(active[(index + 1) % len(active)]))
            widget.bind("<Shift-Tab>", focus_target(active[(index - 1) % len(active)]))
            if isinstance(widget, CTkButton):
                widget.bind("<Return>", lambda _event, button=widget: (button.invoke(), "break")[1])
                widget.bind("<space>", lambda _event, button=widget: (button.invoke(), "break")[1])

    def _role_changed(self, role: str):
        self.role_var = role
        self._show_status(f"အသုံးပြုသူအဆင့်ကို {role} သို့ ပြောင်းထားပါသည်။")

    def _configure_message_tags(self):
        # Fixed tab stops keep Title, separator and Data aligned even when title
        # lengths differ. The values are Tk screen distances (points).
        self.message_box._textbox.configure(tabs=("205p", "230p"))
        self.message_box._textbox.tag_configure(
            "system_label", foreground=UI_COLORS["muted"], font=(UI_FONT_FAMILY, 11, "bold")
        )
        self.message_box._textbox.tag_configure(
            "field_title", foreground=UI_COLORS["field_title"], font=(UI_FONT_FAMILY, 14, "bold")
        )
        self.message_box._textbox.tag_configure(
            "field_separator", foreground=UI_COLORS["muted"], font=(UI_FONT_FAMILY, 14, "bold")
        )
        self.message_box._textbox.tag_configure(
            "field_data", foreground=UI_COLORS["field_data"], font=(UI_FONT_FAMILY, 14)
        )
        self.message_box._textbox.tag_configure(
            "status_complete", foreground=UI_COLORS["status_complete"], font=(UI_FONT_FAMILY, 14, "bold")
        )
        self.message_box._textbox.tag_configure(
            "status_pending", foreground=UI_COLORS["status_pending"], font=(UI_FONT_FAMILY, 14, "bold")
        )
        self.message_box._textbox.tag_configure(
            "status_danger", foreground=UI_COLORS["status_danger"], font=(UI_FONT_FAMILY, 14, "bold")
        )

    def _show_status(self, message: str):
        display_message = burmese_display(message)
        self._message_queue.append(display_message.split("\n"))
        if not self._typing_active:
            self._start_next_message()

    def _insert_message_text(self, text: str, tag: str):
        self.message_box.configure(state="normal")
        self.message_box.insert("end", text, tag)
        self.message_box.see("end")
        self.message_box.configure(state="disabled")

    def _start_next_message(self):
        if not self._message_queue:
            self._typing_active = False
            return
        self._typing_active = True
        lines = self._message_queue.pop(0)
        self._insert_message_text("\n[စနစ်]\n", "system_label")
        self._animate_message_lines(lines, 0)

    def _animate_message_lines(self, lines: List[str], line_index: int):
        if line_index >= len(lines):
            self._typing_active = False
            self.after(80, self._start_next_message)
            return

        line = lines[line_index]
        if ":" in line:
            title, data = line.split(":", 1)
            if title.strip():
                self._insert_message_text(title.strip(), "field_title")
                self._insert_message_text("\t-\t", "field_separator")
                data_value = data.strip()
                data_tag = self._semantic_data_tag(title, data_value)
                if data_tag == "status_danger":
                    self._insert_blinking_danger_bar()
                elif data_tag != "field_data":
                    self._insert_message_text("▌ ", data_tag)
                clusters = self._text_clusters(data_value)
                self.after(70, lambda: self._type_field_data(lines, line_index, clusters, 0, data_tag))
                return

        self._insert_message_text(line + "\n", "field_data")
        self.after(45, lambda: self._animate_message_lines(lines, line_index + 1))

    def _type_field_data(
        self,
        lines: List[str],
        line_index: int,
        clusters: List[str],
        cluster_index: int,
        data_tag: str,
    ):
        if cluster_index >= len(clusters):
            self._insert_message_text("\n", "field_data")
            self.after(65, lambda: self._animate_message_lines(lines, line_index + 1))
            return
        self._insert_message_text(clusters[cluster_index], data_tag)
        self.after(
            self._typing_delay_ms,
            lambda: self._type_field_data(lines, line_index, clusters, cluster_index + 1, data_tag),
        )

    def _insert_blinking_danger_bar(self):
        self._danger_bar_counter += 1
        tag_name = f"danger_bar_{self._danger_bar_counter}"
        self.message_box._textbox.tag_configure(
            tag_name,
            foreground=UI_COLORS["status_danger"],
            font=(UI_FONT_FAMILY, 14, "bold"),
        )
        self._insert_message_text("▌ ", tag_name)
        self.after(260, lambda: self._blink_danger_bar(tag_name, 0))

    def _blink_danger_bar(self, tag_name: str, step: int):
        # Ten pulses draw attention without leaving a distracting
        # permanent animation. The bar always finishes in solid red.
        if step >= 20:
            self.message_box._textbox.tag_configure(
                tag_name, foreground=UI_COLORS["status_danger"]
            )
            return
        visible = step % 2 == 1
        self.message_box._textbox.tag_configure(
            tag_name,
            foreground=UI_COLORS["status_danger"] if visible else UI_COLORS["background"],
        )
        self.after(260, lambda: self._blink_danger_bar(tag_name, step + 1))

    @staticmethod
    def _semantic_data_tag(title: str, data: str) -> str:
        normalized_title = canonical_field(title)
        normalized_data = normalize_text(data)
        if "မဲပေးမှုအခြေအနေ" in normalized_title or "မဲပေးပြီးမပြီး" in normalized_title:
            if normalized_data == normalize_text("ပြီး"):
                return "status_complete"
            if normalized_data == normalize_text("မပြီး"):
                return "status_pending"
        if "ပြစ်မှုမှတ်တမ်း" in normalized_title:
            has_record = normalized_data in {normalize_text("ရှိ"), "yes", "true", "1"}
            if has_record:
                return "status_danger"
        return "field_data"

    @staticmethod
    def _text_clusters(text: str) -> List[str]:
        """Keep Myanmar/Unicode combining marks attached during animation."""
        clusters: List[str] = []
        for character in text:
            category = unicodedata.category(character)
            if clusters and (category.startswith("M") or character in {"\u200c", "\u200d"}):
                clusters[-1] += character
            else:
                clusters.append(character)
        return clusters

    def _focus_chat(self):
        self.input_entry.focus_set()

    def _show_attachment_menu(self):
        popup = CTkToplevel(self)
        popup.title("Attach Input")
        apply_window_icon(popup)
        fit_window_to_screen(popup, 320, 220, 300, 200, 80, 110)
        start_fade_in(popup, steps=8, interval_ms=16)
        upload_button = CTkButton(popup, text="ကတ်ပုံ Upload တင်ရန်", command=lambda: self._upload_image(popup))
        upload_button.pack(fill="x", padx=20, pady=12)
        camera_button = CTkButton(popup, text="Camera ဖြင့် Scan ဖတ်ရန်", command=lambda: self._scan_from_camera(popup))
        camera_button.pack(fill="x", padx=20, pady=12)
        self._bind_tab_order([upload_button, camera_button])
        popup.after(120, upload_button.focus_set)

    def _upload_image(self, popup):
        file = filedialog.askopenfilename(filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp")])
        if not file:
            popup.destroy()
            return
        card = self.ocr.extract_card(file)
        if not card["raw_text"]:
            self._show_status(self.ocr.last_error or "စာသားဖတ်မရပါ။ ကြည်လင်သောပုံကို ပြန်တင်ပါ။")
            popup.destroy()
            return
        self._show_status(f"OCR content loaded from image: {Path(file).name}")
        popup.destroy()
        self._process_ocr_card(card, Path(file).name)

    def _scan_from_camera(self, popup):
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            messagebox.showwarning("Camera Error", "No webcam was detected on this device.")
            popup.destroy()
            return
        ret, frame = cap.read()
        if ret:
            saved_path = PROJECT_ROOT / "captured_id_card.png"
            cv2.imwrite(str(saved_path), frame)
            card = self.ocr.extract_card(str(saved_path))
            if not card["raw_text"]:
                self._show_status(self.ocr.last_error or "စာသားဖတ်မရပါ။")
                cap.release()
                popup.destroy()
                return
            self._show_status("Camera capture completed and OCR text has been prepared.")
            self._process_ocr_card(card, saved_path.name)
        cap.release()
        popup.destroy()

    def _process_ocr_card(self, card: Dict[str, Any], source_name: str):
        fields = card.get("fields", {})
        # Do not present OCR noise as a detected value. A field is kept only when
        # it exists in the corresponding datafile column; the raw OCR remains
        # visible in the review window for manual correction.
        verified_fields: Dict[str, str] = {}
        for key in ("name", "father_name", "id_number"):
            value = fields.get(key, "")
            if value and key in self.current_dataset.columns:
                known_values = self.current_dataset[key].map(canonical_field)
                if canonical_field(value) in set(known_values):
                    verified_fields[key] = value
        fields = verified_fields
        required = ("name", "father_name", "id_number")
        if all(fields.get(key) for key in required):
            self._submit_card_fields(fields, source_name)
            return
        self._show_ocr_review(fields, card.get("raw_text", ""), source_name)

    def _submit_card_fields(self, fields: Dict[str, str], source_name: str):
        result = self.query_engine.evaluate_card(fields, self.role_var)
        self._show_status(result["reply"])
        self.audit_logger.log("card_check", self.current_username, f"Role: {self.role_var} | Source: {source_name}")

    def _show_ocr_review(self, fields: Dict[str, str], raw_text: str, source_name: str):
        review = CTkToplevel(self)
        review.title("OCR အချက်အလက် စစ်ဆေးရန်")
        apply_window_icon(review)
        review_width, _ = fit_window_to_screen(review, 760, 640, 620, 520, 80, 110)
        start_fade_in(review, steps=8, interval_ms=16)
        review.grid_columnconfigure(1, weight=1)
        review.grid_rowconfigure(5, weight=1)

        CTkLabel(
            review,
            text="လက်ရေးစာကို အပြည့်အစုံမဖတ်နိုင်ပါ။ ကတ်ပေါ်ရှိအချက်အလက်နှင့် တိုက်စစ်ပြီး ဖြည့်/ပြင်ပါ။",
            font=(UI_FONT_FAMILY, 16, "bold"), wraplength=review_width - 60, justify="left",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 14), sticky="w")

        definitions = (
            ("name", "အမည်"),
            ("father_name", "ဖခင်အမည်"),
            ("id_number", "မှတ်ပုံတင်အမှတ်"),
        )
        entries: Dict[str, CTkEntry] = {}
        for row_number, (key, label) in enumerate(definitions, start=1):
            CTkLabel(review, text=label).grid(row=row_number, column=0, padx=(20, 10), pady=8, sticky="w")
            entry = CTkEntry(review, height=38)
            entry.grid(row=row_number, column=1, padx=(0, 20), pady=8, sticky="ew")
            if fields.get(key):
                entry.insert(0, fields[key])
            entries[key] = entry

        CTkLabel(review, text="OCR ဖတ်ထားသည့် မူရင်းစာသား").grid(
            row=4, column=0, columnspan=2, padx=20, pady=(14, 6), sticky="w"
        )
        raw_box = CTkTextbox(review, wrap="word", font=(UI_FONT_FAMILY, 12))
        raw_box.grid(row=5, column=0, columnspan=2, padx=20, pady=(0, 14), sticky="nsew")
        raw_box.insert("end", raw_text or "OCR စာသားမရပါ။")
        raw_box.configure(state="disabled")

        button_bar = CTkFrame(review, fg_color="transparent")
        button_bar.grid(row=6, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="e")

        def confirm_fields():
            corrected = {key: entry.get().strip() for key, entry in entries.items()}
            missing = [label for key, label in definitions if not corrected[key]]
            if missing:
                messagebox.showwarning("အချက်အလက် မပြည့်စုံပါ", "ဖြည့်ရန်လိုသည်: " + "၊ ".join(missing), parent=review)
                return
            review.destroy()
            self._submit_card_fields(corrected, source_name)

        cancel_button = CTkButton(button_bar, text="ပယ်ဖျက်", fg_color="#64748b", command=review.destroy)
        cancel_button.pack(side="left", padx=(0, 8))
        confirm_button = CTkButton(button_bar, text="တိုက်စစ်မည်", command=confirm_fields)
        confirm_button.pack(side="left")
        review_order = list(entries.values()) + [cancel_button, confirm_button]
        self._bind_tab_order(review_order)
        entries["id_number"].bind("<Return>", lambda _event: (confirm_fields(), "break")[1])
        review.after(120, entries["name"].focus_set)
        review.after(100, review.lift)
        review.grab_set()

    def _handle_chat_submit(self, ocr_result: str = ""):
        raw_query = ocr_result if ocr_result else self.input_entry.get().strip()
        self.input_entry.delete(0, "end")
        if not raw_query:
            self._show_status("အမည်၊ မှတ်ပုံတင်နောက်ဆုံးဂဏန်း ၆ လုံး သို့မဟုတ် အဘအမည်ကို ရိုက်ထည့်ပါ။")
            return

        if ocr_result:
            fields = self.ocr._parse_structured_fields(raw_query)
            if all(fields.get(key) for key in ("name", "father_name", "id_number")):
                self._submit_card_fields(fields, "OCR text")
            else:
                self._show_ocr_review(fields, raw_query, "OCR text")
            return

        normalized_query = normalize_text(raw_query)
        query_digits = "".join(re.findall(r"\d", normalized_query))
        numeric_only = bool(re.fullmatch(r"[0-9\s]+", normalized_query))
        if numeric_only:
            if len(query_digits) != 6:
                self._show_status("မှတ်ပုံတင်နောက်ဆုံးဂဏန်း ၆ လုံးတိတိ ရိုက်ထည့်ပါ။")
                return
            result = self.query_engine.evaluate_id_last_six(query_digits, self.role_var)
        else:
            result = self.query_engine.evaluate_query(raw_query, self.role_var)

        if result.get("status") == "multiple_matches":
            self._show_match_choices(result["matches"])
            return

        if result.get("status") == "no_match":
            self._show_status(result.get("message", "မည်သည့်အချက်အလက်ကိုမှ တူညီမှုမတွေ့ရှိပါ။"))
            self.audit_logger.log("query", self.current_username, f"Role: {self.role_var} | {raw_query}")
            return

        if result.get("status") == "match":
            response = result.get("reply", "အချက်အလက်တွေ့ရှိပါသည်။")
            self._show_status(f"ရှာဖွေမှု: {raw_query}\n\n{response}")
            self.audit_logger.log("query", self.current_username, f"Role: {self.role_var} | {raw_query} -> {response}")

    def _show_match_choices(self, matches: List[Dict[str, Any]]):
        if self.choice_frame is not None:
            self.choice_frame.destroy()

        self.choice_frame = CTkFrame(
            self.chat_tab, fg_color=UI_COLORS["surface_alt"], corner_radius=12,
            border_width=1, border_color=UI_COLORS["border"],
        )
        self.choice_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
        self.choice_frame.grid_columnconfigure(0, weight=1)

        CTkLabel(
            self.choice_frame,
            text="ကိုက်ညီသောမှတ်တမ်းများရှိပါသည်။ ↑/↓ ရွေးရန် • Enter အတည်ပြုရန် • Esc ပယ်ဖျက်ရန်",
            font=(UI_FONT_FAMILY, 16, "bold"),
        ).grid(row=0, column=0, padx=16, pady=(16, 12), sticky="w")

        self.choice_matches = matches
        self.choice_buttons = []
        self.choice_index = 0
        for idx, match in enumerate(matches):
            label = (
                f"အမည် - {match['name']}   |   အဘအမည် - {match['father_name']}\n"
                f"မှတ်ပုံတင် - {match['id_number']}   |   မဲစာရင်းအမှတ် - {match['voter_no']}"
            )
            btn = CTkButton(
                self.choice_frame,
                text=burmese_display(label),
                command=lambda i=idx: self._confirm_match_choice(matches[i]),
                anchor="w",
                fg_color=UI_COLORS["surface"],
                hover_color=UI_COLORS["primary_hover"],
                border_width=1,
                border_color=UI_COLORS["border"],
                height=58,
                corner_radius=10,
                font=(UI_FONT_FAMILY, 12),
            )
            btn.grid(row=idx + 1, column=0, padx=16, pady=(0, 8), sticky="ew")
            btn.bind("<Up>", lambda _event: self._move_match_choice(-1))
            btn.bind("<Down>", lambda _event: self._move_match_choice(1))
            btn.bind("<Return>", lambda _event: self._confirm_selected_match())
            self.choice_buttons.append(btn)
        self._bind_tab_order(self.choice_buttons)
        # Override the generic button Enter binding so it always confirms the
        # item highlighted by the arrow-key selection.
        for button in self.choice_buttons:
            button.bind("<Return>", lambda _event: self._confirm_selected_match())
            button.bind("<Escape>", self._cancel_match_choices)
        self.bind("<Escape>", self._cancel_match_choices)
        if self.choice_buttons:
            self._set_match_choice(0)
            self.after(80, self.choice_buttons[0].focus_set)

    def _set_match_choice(self, index: int):
        if not self.choice_buttons:
            return
        self.choice_index = index % len(self.choice_buttons)
        for button_index, button in enumerate(self.choice_buttons):
            selected = button_index == self.choice_index
            button.configure(
                fg_color=UI_COLORS["primary"] if selected else UI_COLORS["surface"],
                border_color="#93C5FD" if selected else UI_COLORS["border"],
            )
        self.choice_buttons[self.choice_index].focus_set()

    def _move_match_choice(self, step: int):
        self._set_match_choice(self.choice_index + step)
        return "break"

    def _confirm_selected_match(self):
        if self.choice_matches:
            self._confirm_match_choice(self.choice_matches[self.choice_index])
        return "break"

    def _cancel_match_choices(self, _event=None):
        if self.choice_frame is None:
            return "break"
        self.choice_frame.destroy()
        self.choice_frame = None
        self.choice_buttons = []
        self.choice_matches = []
        self.choice_index = 0
        self.unbind("<Escape>")
        self._show_status("အမည်တူရွေးချယ်မှုကို ပယ်ဖျက်လိုက်ပါသည်။")
        self.after(80, self.input_entry.focus_set)
        return "break"

    def _confirm_match_choice(self, match_item: Dict[str, Any]):
        row = self.current_dataset.loc[match_item["row_index"]]
        response = self.query_engine.format_candidate(row, self.role_var)

        if self.choice_frame is not None:
            self.choice_frame.destroy()
            self.choice_frame = None
        self.unbind("<Escape>")
        self.choice_buttons = []
        self.choice_matches = []
        self.choice_index = 0

        self._show_status("ရွေးချယ်ထားသော မဲဆန္ဒရှင်\n\n" + response)
        self.audit_logger.log("selection", self.current_username, f"Role: {self.role_var} | {row.get('father_name', '')} | {row.get('id_number', '')}")

    def _train_model(self):
        if self.role_var not in {"Admin", "Super Admin"}:
            self._show_status("ဤလုပ်ဆောင်ချက်ကို Admin သို့မဟုတ် Super Admin သာ အသုံးပြုနိုင်ပါသည်။")
            return
        file = filedialog.askopenfilename(filetypes=[("CSV/Excel", "*.csv;*.xlsx;*.xls")])
        if not file:
            return
        try:
            dataset = self.dataset_manager.load(Path(file))
            artifact = self.model_manager.train_and_save(dataset)
            self.current_dataset = dataset
            self.query_engine = VoterQueryEngine(self.current_dataset, self.model_manager)
            self._refresh_model_status(artifact)
            self._show_status(f"Model trained successfully using {len(dataset)} records. Accuracy: {artifact['training_accuracy']:.3f}")
            self.audit_logger.log("training", self.current_username, f"Role: {self.role_var} | Dataset file: {file}")
        except Exception as exc:
            messagebox.showerror("Training Error", str(exc))

    def _refresh_model_status(self, artifact: Optional[Dict[str, Any]] = None):
        if artifact is None and self.model_manager.model_path.exists():
            try:
                artifact = self.model_manager.load_model()
            except Exception:
                artifact = {}
        self.model_stats.configure(state="normal")
        self.model_stats.delete("1.0", "end")
        if not artifact:
            self.model_stats.insert("end", "Model not trained yet.\n")
        else:
            self.model_stats.insert("end", f"Rows: {artifact.get('source_rows', 0)}\n")
            self.model_stats.insert("end", f"Training accuracy: {artifact.get('training_accuracy', 0):.3f}\n")
            self.model_stats.insert("end", f"Features: {artifact.get('feature_cols', [])}\n")
            self.model_stats.insert("end", f"Categories: {artifact.get('categorical_cols', [])}\n")
        self.model_stats.configure(state="disabled")

    def _open_dataset_panel(self):
        if self.role_var not in {"Admin", "Super Admin"}:
            self._show_status("ဤလုပ်ဆောင်ချက်ကို Admin သို့မဟုတ် Super Admin သာ အသုံးပြုနိုင်ပါသည်။")
            return
        self._show_status("Dataset manager opened. Use the Train Model button to upload a CSV or Excel file.")

    def _open_accounts_panel(self):
        if self.role_var != "Super Admin":
            self._show_status("Account စီမံခန့်ခွဲမှုကို Super Admin သာ အသုံးပြုနိုင်ပါသည်။")
            return
        account_window = CTkToplevel(self)
        account_window.title("Account Management")
        apply_window_icon(account_window)
        fit_window_to_screen(account_window, 680, 460, 600, 420, 80, 110)
        start_fade_in(account_window, steps=8, interval_ms=16)

        CTkLabel(
            account_window, text="Create User / Admin Account",
            font=(UI_FONT_FAMILY, 18, "bold"), anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="ew")

        username_entry = CTkEntry(account_window, width=260)
        password_entry = CTkEntry(account_window, show="*", width=260)
        role_option = CTkOptionMenu(account_window, values=["User", "Admin", "Super Admin"]) 
        role_option.set("User")

        CTkLabel(account_window, text="Username").grid(row=1, column=0, padx=(20, 8), pady=8, sticky="w")
        username_entry.grid(row=1, column=1, padx=(0, 20), pady=8, sticky="ew")
        CTkLabel(account_window, text="Password").grid(row=2, column=0, padx=(20, 8), pady=8, sticky="w")
        password_entry.grid(row=2, column=1, padx=(0, 20), pady=8, sticky="ew")
        CTkLabel(account_window, text="Role").grid(row=3, column=0, padx=(20, 8), pady=8, sticky="w")
        role_option.grid(row=3, column=1, padx=(0, 20), pady=8, sticky="ew")

        def create_account():
            try:
                username = username_entry.get().strip()
                password = password_entry.get().strip()
                role = role_option.get()
                self.account_manager.create_account(username, password, role)
                self.audit_logger.log("account_create", username, f"Role: {role}")
                self._render_account_summary()
                self._show_status(f"Account created: {username} ({role})")
                account_window.destroy()
            except Exception as exc:
                messagebox.showerror("Account Error", str(exc))

        create_button = CTkButton(account_window, text="Create Account", command=create_account)
        create_button.grid(row=4, column=1, sticky="e", padx=(0, 20), pady=(12, 16))
        self._bind_tab_order([username_entry, password_entry, role_option, create_button])
        password_entry.bind("<Return>", lambda _event: (create_account(), "break")[1])
        account_window.after(120, username_entry.focus_set)

    def _open_logs_panel(self):
        if self.role_var not in {"Admin", "Super Admin"}:
            self._show_status("လုပ်ဆောင်မှုမှတ်တမ်းကို Admin သို့မဟုတ် Super Admin သာ ကြည့်နိုင်ပါသည်။")
            return
        log_window = CTkToplevel(self)
        log_window.title("Audit Logs")
        apply_window_icon(log_window)
        fit_window_to_screen(log_window, 920, 560, 700, 460, 80, 110)
        start_fade_in(log_window, steps=8, interval_ms=16)
        logs = self.audit_logger.get_logs()
        text = "\n".join(f"[{item.get('timestamp', '')}] {item.get('username', '')} - {item.get('action', '')}: {item.get('details', '')}" for item in logs)
        box = CTkTextbox(log_window, wrap="word")
        box.pack(fill="both", expand=True, padx=18, pady=18)
        box.insert("end", text or "No logs recorded yet.")
        box.configure(state="disabled")

    def _render_account_summary(self):
        self.account_panel.grid_forget()
        self.account_panel = CTkScrollableFrame(self.info_panel, corner_radius=12)
        self.account_panel.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 10))
        self.account_panel.grid_columnconfigure(0, weight=1)
        if self.role_var != "Super Admin":
            CTkLabel(
                self.account_panel,
                text=f"Login ဝင်ထားသူ\n{self.current_username}\n\nRole\n{self.role_var}",
                anchor="w", justify="left", text_color=UI_COLORS["muted"],
            ).grid(row=0, column=0, padx=10, pady=12, sticky="w")
            return
        accounts = self.account_manager.list_accounts()
        if not accounts:
            CTkLabel(self.account_panel, text="No accounts created yet.", anchor="w").grid(row=0, column=0, padx=10, pady=8, sticky="w")
            return
        for index, account in enumerate(accounts):
            CTkLabel(self.account_panel, text=f"{account.get('username', '')} [{account.get('role', 'User')}]", anchor="w").grid(row=index, column=0, sticky="ew", padx=10, pady=6)


if __name__ == "__main__":
    from login import run_application

    run_application()
