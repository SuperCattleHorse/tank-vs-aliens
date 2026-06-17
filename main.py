"""
Tank vs Aliens 3D -- entry point.

Run with:  python main.py   (use your Python 3.11 environment)

Main menu -> Start Game / Quit. In-game: WASD move, mouse aim, left-click fire,
Esc returns to the main menu. On death a game-over panel shows your score.
"""
import math

from ursina import (
    Ursina, Entity, Text, Button, camera, color, window, mouse, application,
    destroy, Func, invoke, time,
)

from game import Game
from audio import play_sound

app = Ursina(title="Tank vs Aliens 3D", borderless=False, fullscreen=False,
             development_mode=False, vsync=True)
window.color = color.hsv(222, 0.50, 0.07)
window.fps_counter.enabled = False
window.exit_button.visible = False

# shared mutable state across the screen-transition callbacks
state = {"game": None, "menu": None, "music": None, "win_size": None, "win_pos": None}


# ------------------------------------------------------------------ keep window
def _snapshot_window():
    """Remember the window's current on-screen size and position."""
    try:
        props = application.base.win.getProperties()
        if props.hasSize():
            state["win_size"] = (props.getXSize(), props.getYSize())
        if props.hasOrigin():
            state["win_pos"] = (props.getXOrigin(), props.getYOrigin())
    except Exception:
        pass


def _restore_window():
    """Re-assert the remembered geometry if a screen change disturbed it."""
    try:
        props = application.base.win.getProperties()
        size, pos = state.get("win_size"), state.get("win_pos")
        if size and props.hasSize() and (props.getXSize(), props.getYSize()) != tuple(size):
            window.size = size
        if pos and props.hasOrigin() and (props.getXOrigin(), props.getYOrigin()) != tuple(pos):
            window.position = pos
    except Exception:
        pass


def _keep_window():
    """Snapshot the geometry now and re-apply it a few frames later, so that
    entering the game or returning to a menu never resizes or moves the window."""
    _snapshot_window()
    invoke(_restore_window, delay=0.12)


# --------------------------------------------------------------------------- bg
def _start_music():
    if state["music"] is None:
        state["music"] = play_sound("background", volume=0.30, loop=True,
                                    autoplay=True, auto_destroy=False)


# --------------------------------------------------------------------- palette
TITLE_GOLD   = color.hsv(45, 0.85, 1.00)
TITLE_SHADOW = color.hsv(222, 0.60, 0.05)
ACCENT_CYAN  = color.hsv(190, 0.55, 0.96)
SUBTLE_TEXT  = color.hsv(210, 0.20, 0.80)
PANEL_BG     = color.hsv(222, 0.55, 0.05)

BTN_GREEN    = color.hsv(140, 0.55, 0.60)
BTN_GREEN_HI = color.hsv(140, 0.55, 0.80)
BTN_BLUE     = color.hsv(210, 0.55, 0.70)
BTN_BLUE_HI  = color.hsv(200, 0.60, 0.88)
BTN_RED      = color.hsv(5, 0.70, 0.60)
BTN_RED_HI   = color.hsv(20, 0.85, 0.78)


def _menu_button(text, parent, y, base, hi, text_color, on_click):
    """A consistently styled menu button."""
    return Button(text, parent=parent, scale=(0.34, 0.095), position=(0, y),
                  color=base, highlight_color=hi, text_color=text_color,
                  on_click=on_click)


class RotatingUFO(Entity):
    """Decorative UFO with smooth continuous rotation matching in-game style."""
    def __init__(self, parent, position=(0, 0.40), scale=0.18):
        super().__init__(parent=parent, position=position)
        self.rotation_speed = 60  # degrees per second
        
        Entity(parent=self, model="sphere", color=color.hsv(210, 0.10, 0.80),
               scale=(2.6 * scale, 0.5 * scale, 2.6 * scale))
        Entity(parent=self, model="sphere", color=color.hsv(210, 0.10, 0.80),
               scale=(1.8 * scale, 0.35 * scale, 1.8 * scale), y=-0.15 * scale)
        Entity(parent=self, model="sphere", color=color.hsv(195, 0.60, 0.95),
               scale=(1.2 * scale, 1.0 * scale, 1.2 * scale), y=0.35 * scale, alpha=0.85)
        self.lights = Entity(parent=self, y=-0.2 * scale)
        for i in range(6):
            a = i / 6 * math.tau
            Entity(parent=self.lights, model="sphere", color=color.lime, scale=0.22 * scale,
                   position=(math.cos(a) * 1.0 * scale, 0, math.sin(a) * 1.0 * scale))
    
    def update(self):
        self.lights.rotation_y += self.rotation_speed * time.dt


# ------------------------------------------------------------------- main menu
def show_main_menu():
    _keep_window()
    _clear_menu()
    _start_music()
    mouse.visible = True

    menu = Entity(parent=camera.ui)

    # soft backdrop panel to frame the menu
    Entity(parent=menu, model="quad", color=PANEL_BG, alpha=0.5, scale=(0.98, 1.1))

    # decorative UFO in the center (above title) with continuous smooth rotation
    RotatingUFO(menu)

    # title with a drop shadow for legibility
    Text("TANK  vs  ALIENS", parent=menu, origin=(0, 0), position=(0.006, 0.272),
         scale=3.4, color=TITLE_SHADOW)
    Text("TANK  vs  ALIENS", parent=menu, origin=(0, 0), position=(0, 0.28),
         scale=3.4, color=TITLE_GOLD)
    Text("3 D", parent=menu, origin=(0, 0), position=(0, 0.16), scale=1.7,
         color=ACCENT_CYAN)
    Text("Defend Earth -- blast the saucers and the alien horde.",
         parent=menu, origin=(0, 0), position=(0, 0.07), scale=1.0,
         color=SUBTLE_TEXT)

    _menu_button("START  GAME", menu, -0.085, BTN_GREEN, BTN_GREEN_HI,
                 color.black, start_game)
    _menu_button("QUIT", menu, -0.215, BTN_RED, BTN_RED_HI,
                 color.white, quit_game)

    Text("WASD move      Mouse aim      Left-Click fire      Esc pause",
         parent=menu, origin=(0, 0), position=(0, -0.40), scale=0.85,
         color=SUBTLE_TEXT)

    state["menu"] = menu


def _clear_menu():
    if state["menu"] is not None:
        destroy(state["menu"])
        state["menu"] = None


# ----------------------------------------------------------------- transitions
def start_game():
    play_sound("ui_click", volume=0.6)
    _keep_window()
    _clear_menu()
    if state["game"] is not None:
        state["game"].teardown()
        state["game"] = None
    state["game"] = Game(on_game_over=show_game_over, on_exit=return_to_menu)


def return_to_menu():
    # called by the in-game pause menu's "Main Menu" button
    if state["game"] is not None:
        state["game"].teardown()
        state["game"] = None
    show_main_menu()


def show_game_over(score):
    _keep_window()
    if state["game"] is not None:
        state["game"].teardown()
        state["game"] = None
    _clear_menu()
    mouse.visible = True

    menu = Entity(parent=camera.ui)
    Entity(parent=menu, model="quad", color=PANEL_BG, alpha=0.72, scale=(0.82, 0.92))

    Text("GAME  OVER", parent=menu, origin=(0, 0), position=(0.006, 0.262),
         scale=3.0, color=TITLE_SHADOW)
    Text("GAME  OVER", parent=menu, origin=(0, 0), position=(0, 0.27),
         scale=3.0, color=color.hsv(5, 0.80, 0.98))
    Text("FINAL SCORE", parent=menu, origin=(0, 0), position=(0, 0.13),
         scale=1.1, color=SUBTLE_TEXT)
    Text(f"{score}", parent=menu, origin=(0, 0), position=(0, 0.04),
         scale=2.8, color=TITLE_GOLD)

    _menu_button("PLAY  AGAIN", menu, -0.10, BTN_GREEN, BTN_GREEN_HI,
                 color.black, start_game)
    _menu_button("MAIN  MENU", menu, -0.23, BTN_BLUE, BTN_BLUE_HI,
                 color.white, show_main_menu)
    _menu_button("QUIT", menu, -0.36, BTN_RED, BTN_RED_HI,
                 color.white, quit_game)

    state["menu"] = menu


def quit_game():
    play_sound("ui_click", volume=0.6)
    application.quit()


# ----------------------------------------------------------------------- input
def input(key):
    # In-game, Esc is handled by Game.input (it pauses). Here we only handle the
    # menu screens, where there is no active run to pause.
    if key == "escape" and state["game"] is None:
        application.quit()


show_main_menu()
app.run()
