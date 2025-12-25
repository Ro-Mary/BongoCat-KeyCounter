import json, os, math, sys, time
import keyboard as kb
from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QPixmap, QTransform, QPainter, QFont, QColor, QIcon
from PySide6.QtWidgets import QApplication, QWidget
from pynput import keyboard as pk, mouse as pm

def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)

def app_dir():
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
           else os.path.dirname(os.path.abspath(__file__))

def normalize_token(name: str) -> str:
    n = (name or "").lower()
    alias = {
        "control": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
        "shift_l": "shift", "shift_r": "shift",
        "alt_l": "alt", "alt_r": "alt",
        "windows": "cmd", "win": "cmd",
        "escape": "esc",
    }
    return alias.get(n, n)

def parse_combo(s: str) -> frozenset[str]:
    if not s:
        return frozenset()
    parts = [normalize_token(p) for p in s.split("+") if p]
    return frozenset(parts)

W, H = 393, 252
PKG_ASSETS = resource_path("img")
IMG_BG1 = os.path.join(PKG_ASSETS, "bg1.png")
IMG_BG2 = os.path.join(PKG_ASSETS, "bg2.png")
IMG_BG3 = os.path.join(PKG_ASSETS, "bg3.png")
IMG_SKILL1 = os.path.join(PKG_ASSETS, "skill1.png")
IMG_SKILL2 = os.path.join(PKG_ASSETS, "skill2.png")
APP_ICON = os.path.join(PKG_ASSETS, "icon.ico")

POS_SKILL1 = (94, 182)
POS_SKILL2 = (273, 183)
POS_COUNT1 = (77, 215)
POS_COUNT2 = (260, 215)

ICON_BASE_H = 55
H_STRETCH_SKILL1 = 1.5
H_STRETCH_SKILL2 = 1.5
SKEW_DEG = -33

CONFIG_PATH = os.path.join(app_dir(), "counter_config.json")
EXE_ASSETS = os.path.join(app_dir(), "img")

# skill 아이콘은 exe 옆 assets 우선, 없으면 번들 기본으로 폴백
def skill_path(name: str) -> str:
    p1 = os.path.join(EXE_ASSETS, name)
    if os.path.exists(p1):
        return p1
    return os.path.join(PKG_ASSETS, name) 

DEFAULT_CONFIG = {
    "keys": ["q", "e"],
    "counts": {"key1": 0, "key2": 0},
    "delay": {"key1": 2.1, "key2": 2.1}
}

def load_config():
    changed = False
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            conf = json.load(f)
    except Exception:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        return DEFAULT_CONFIG.copy()

    keys = [str(k).lower() for k in conf.get("keys", [])[:2]]
    if len(keys) != 2 or keys[0] == keys[1]:
        keys = DEFAULT_CONFIG["keys"]; changed = True

    raw_counts = conf.get("counts", {})
    if "key1" in raw_counts and "key2" in raw_counts:
        counts = {"key1": int(raw_counts.get("key1", 0)),
                  "key2": int(raw_counts.get("key2", 0))}
    else:
        c1 = int(raw_counts.get(keys[0], 0))
        c2 = int(raw_counts.get(keys[1], 0))
        counts = {"key1": c1, "key2": c2}
        changed = True

    raw_delay = conf.get("delay", {})
    delay = {
        "key1": float(raw_delay.get("key1", DEFAULT_CONFIG["delay"]["key1"])),
        "key2": float(raw_delay.get("key2", DEFAULT_CONFIG["delay"]["key2"])),
    }
    delay["key1"] = max(0.0, delay["key1"])
    delay["key2"] = max(0.0, delay["key2"])
    if "delay" not in conf: changed = True

    fixed = {"keys": keys, "counts": counts, "delay": delay}
    if changed:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(fixed, f, ensure_ascii=False, indent=2)

    return fixed

def save_config(keys, counts, delay):
    data = {"keys": keys, "counts": counts, "delay": delay}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_pixmap(path, size: QSize | None = None):
    if os.path.exists(path):
        pm = QPixmap(path)
        if size:
            pm = pm.scaled(
                size, 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
        return pm
    pm = QPixmap(64, 64); pm.fill(Qt.transparent); return pm

def make_icon_pixmap(path, h_stretch=1.0, skew_deg=SKEW_DEG):
    pm = load_pixmap(path)
    if pm.isNull():
        pm = QPixmap(ICON_BASE_H, ICON_BASE_H); pm.fill(Qt.transparent)

    # 높이 기준
    w, h = pm.width(), pm.height()
    if h > 0:
        pm = pm.scaled(
            int(w * ICON_BASE_H / h),
            ICON_BASE_H,
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation)
    # 가로 늘리기
    if abs(h_stretch - 1.0) > 1e-3:
        pm = pm.scaled(
            int(pm.width() * h_stretch), 
            pm.height(),
            Qt.IgnoreAspectRatio, 
            Qt.SmoothTransformation)
    # 기울이기
    if abs(skew_deg) > 1e-3:
        kx = math.tan(math.radians(skew_deg))
        t = QTransform()
        t.shear(kx, 0.0)
        pm = pm.transformed(t, Qt.SmoothTransformation)
    return pm

class GlobalKeyListener(QThread):
    keyPressed = Signal(str)     
    keyReleased = Signal(str)

    def __init__(self, keys=('q','e')):
        super().__init__()
        self.keys = set(k.lower() for k in keys)
        self._pressed = set()
        self._kb_listener = None
        self._ms_listener = None
        self._use_keyboard_lib = sys.platform.startswith("win")
        self._stop = False
        
    def _norm_key(self, key):
        # 문자키
        ch = getattr(key, "char", None)
        if ch:
            if len(ch) == 1 and "a" <= ch.lower() <= "z":
                return normalize_token(ch)

        # 이름키
        name = getattr(key, "name", None)
        if name:
            return normalize_token(name)

        vk = getattr(key, "vk", None)
        if vk is not None:
                # A(65) ~ Z(90)
            if 65 <= vk <= 90:
                return normalize_token(chr(vk).lower())
            
            # 숫자패드
            keypad_map = {
                96: "num0", 97: "num1", 98: "num2", 99: "num3", 100: "num4",
                101: "num5", 102: "num6", 103: "num7", 104: "num8", 105: "num9",
                110: "num_decimal", 106: "num_multiply", 107: "num_add",
                109: "num_subtract", 111: "num_divide",
            }
            if vk in keypad_map:
                return normalize_token(keypad_map[vk])

        return None
        
    def _norm_mouse(self, button):
        if button == pm.Button.left:   name = "mouse_left"
        elif button == pm.Button.right:  name = "mouse_right"
        elif button == pm.Button.middle: name = "mouse_middle"
        elif str(button).endswith(".x1"):          name = "mouse4"
        elif str(button).endswith(".x2"):          name = "mouse5"
        else: return None
        return normalize_token(name)

    def run(self):
        def on_kb_press(key):
            k = self._norm_key(key)
            if k and k in self.keys and k not in self._pressed:
                self._pressed.add(k); self.keyPressed.emit(k)

        def on_kb_release(key):
            k = self._norm_key(key)
            if k and k in self.keys:
                if k in self._pressed: self._pressed.remove(k)
                self.keyReleased.emit(k)

        def on_ms_click(x, y, button, pressed):
            k = self._norm_mouse(button)
            if not k or k not in self.keys: return
            if pressed:
                if k not in self._pressed:
                    self._pressed.add(k); self.keyPressed.emit(k)
            else:
                if k in self._pressed: self._pressed.remove(k)
                self.keyReleased.emit(k)

        # pynput 리스너 시작
        kbl = pk.Listener(on_press=on_kb_press, on_release=on_kb_release)
        msl = pm.Listener(on_click=on_ms_click)
        kbl.start(); msl.start()
        self._kb_listener, self._ms_listener = kbl, msl

        if self._use_keyboard_lib:
            def kb_on_press(e):
                name = normalize_token(e.name or "")
                if not name: return
                name = name.replace("num ", "num").replace(" ", "_")
                if name in self.keys and name not in self._pressed:
                    self._pressed.add(name); self.keyPressed.emit(name)

            def kb_on_release(e):
                name = normalize_token(e.name or "")
                if not name: return
                name = name.replace("num ", "num").replace(" ", "_")
                if name in self.keys:
                    if name in self._pressed: self._pressed.remove(name)
                    self.keyReleased.emit(name)

            kb.on_press(kb_on_press, suppress=False)
            kb.on_release(kb_on_release, suppress=False)

        while not self._stop:
            self.msleep(100)

        try:
            if self._kb_listener: self._kb_listener.stop()
            if self._ms_listener: self._ms_listener.stop()
            if self._use_keyboard_lib: kb.unhook_all()
        except: pass

    def stop(self):
        self._stop = True


class Canvas(QWidget):
    def __init__(self, keys, counts):
        super().__init__()
        self.setFixedSize(W, H)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self._drag_offset = None

        self.keys = keys
        self.counts = counts
        self.font = QFont("Calibri", 22, QFont.Bold)

        self.bg1 = load_pixmap(IMG_BG1, QSize(W, H))
        self.bg2 = load_pixmap(IMG_BG2, QSize(W, H))
        self.bg3 = load_pixmap(IMG_BG3, QSize(W, H))
        self.bg_current = 3  

        self.icon1 = make_icon_pixmap(skill_path("skill1.png"), H_STRETCH_SKILL1, SKEW_DEG)
        self.icon2 = make_icon_pixmap(skill_path("skill2.png"), H_STRETCH_SKILL2, SKEW_DEG)

    # 드래그
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if (e.buttons() & Qt.LeftButton) and self._drag_offset is not None:
            self.window().move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = None
            e.accept()


    def set_bg(self, which:int):
        self.bg_current = which
        self.update()

    def increment(self, which_key:str):
        self.counts[which_key] = self.counts.get(which_key, 0) + 1
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 아이콘
        x1, y1 = POS_SKILL1
        x2, y2 = POS_SKILL2
        p.drawPixmap(x1 - self.icon1.width()//2, y1 - self.icon1.height()//2, self.icon1)
        p.drawPixmap(x2 - self.icon2.width()//2, y2 - self.icon2.height()//2, self.icon2)

        # 고양이
        if self.bg_current == 1:
            p.drawPixmap(0, 0, self.bg1)
        elif self.bg_current == 2:
            p.drawPixmap(0, 0, self.bg2)
        else:
            p.drawPixmap(0, 0, self.bg3)

        # 텍스트
        p.setFont(self.font)
        p.setPen(QColor("black"))

        c1x, c1y = POS_COUNT1
        c2x, c2y = POS_COUNT2

        txt1 = str(self.counts.get("key1", 0))
        txt2 = str(self.counts.get("key2", 0))

        r1 = p.boundingRect(0, 0, 1000, 1000, Qt.TextSingleLine, txt1)
        r2 = p.boundingRect(0, 0, 1000, 1000, Qt.TextSingleLine, txt2)
        
        p.drawText(c1x - r1.width()//2, c1y + r1.height()//2, txt1)
        p.drawText(c2x - r2.width()//2, c2y + r2.height()//2, txt2)

        p.end()

class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Key-Counter")
        self.setFixedSize(W, H)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._drag_pos = None

        self.ensure_user_skill_icons()
        
        cfg = load_config()
        self.keys = cfg["keys"]
        self.counts = cfg["counts"]
        self.delay = cfg["delay"]

        # 조합 파싱
        self.combo1 = parse_combo(self.keys[0])
        self.combo2 = parse_combo(self.keys[1])

        self._down = set()
        self._latched = {"key1": False, "key2": False}
        self._last_accept = {"key1": 0.0, "key2": 0.0}

        # 관찰 토큰
        watch_tokens = set(self.combo1) | set(self.combo2)

        self.canvas = Canvas(self.keys, self.counts)
        self.canvas.setParent(self)   

        # 키 리스너 생성 시 관찰 토큰 전달
        self.gkh = GlobalKeyListener(keys=watch_tokens)
        self.gkh.keyPressed.connect(self._on_global_key_down)
        self.gkh.keyReleased.connect(self._on_global_key_up)
        self.gkh.start()

        self.setFocusPolicy(Qt.NoFocus)

    def ensure_user_skill_icons(self):
        os.makedirs(EXE_ASSETS, exist_ok=True)
        for name in ("skill1.png", "skill2.png"):
            dst = os.path.join(EXE_ASSETS, name)
            if not os.path.exists(dst):
                src = os.path.join(PKG_ASSETS, name)
                try:
                    with open(src, "rb") as s, open(dst, "wb") as d:
                        d.write(s.read())
                except Exception:
                    pass

    def _on_global_key_down(self, k: str):
        #print("DOWN:", k, "down-set:", self._down)
        self._down.add(k)
        now = time.monotonic()

        if self.combo1.issubset(self._down) and not self._latched["key1"]:
            role = "key1"
            if now - self._last_accept[role] >= self.delay.get(role, 0.0):
                self.counts[role] = self.counts.get(role, 0) + 1
                self._last_accept[role] = now
                self._latched[role] = True
                self.canvas.set_bg(1)
                self.canvas.update()
                save_config(self.keys, self.counts, self.delay)

        if self.combo2.issubset(self._down) and not self._latched["key2"]:
            role = "key2"
            if now - self._last_accept[role] >= self.delay.get(role, 0.0):
                self.counts[role] = self.counts.get(role, 0) + 1
                self._last_accept[role] = now
                self._latched[role] = True
                self.canvas.set_bg(2)
                self.canvas.update()
                save_config(self.keys, self.counts, self.delay)

    def _on_global_key_up(self, k: str):
        if k in self._down:
            self._down.remove(k)

        changed = False
        if self._latched["key1"] and not self.combo1.issubset(self._down):
            self._latched["key1"] = False; changed = True
        if self._latched["key2"] and not self.combo2.issubset(self._down):
            self._latched["key2"] = False; changed = True

        if changed:
            self.canvas.set_bg(3)
            self.canvas.update()

    def closeEvent(self, e):
        try:
            self.gkh.stop()
            self.gkh.wait(1000)
        except Exception:
            pass
        save_config(self.keys, self.counts, self.delay)
        super().closeEvent(e)

def main():  
    os.makedirs(PKG_ASSETS, exist_ok=True)
    app = QApplication(sys.argv)

    if os.path.exists(APP_ICON):
        app.setWindowIcon(QIcon(APP_ICON))

    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YourCompany.YourApp.KeyCounter")
        except Exception:
            pass

    win = Window()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

