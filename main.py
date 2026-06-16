"""
Tank vs Aliens 3D -- entry point.

Run with:  python main.py   (use your Python 3.11 environment)

Main menu -> Start Game / Quit. In-game: WASD move, mouse aim, left-click fire,
Esc returns to the main menu. On death a game-over panel shows your score.
"""
from ursina import (
    Ursina, Entity, Text, Button, camera, color, window, mouse, application,
    destroy, Func, time,
)

from game import Game
from audio import play_sound

app = Ursina(title="Tank vs Aliens 3D", borderless=False, fullscreen=False,
             development_mode=False, vsync=True)
window.color = color.hsv(220, 0.35, 0.10)
window.fps_counter.enabled = False
window.exit_button.visible = False

# shared mutable state across the screen-transition callbacks
state = {"game": None, "menu": None, "music": None}


# --------------------------------------------------------------------------- bg
def _start_music():
    if state["music"] is None:
        state["music"] = play_sound("background", volume=0.30, loop=True,
                                    autoplay=True, auto_destroy=False)


# ------------------------------------------------------------------- main menu
def show_main_menu():
    _clear_menu()
    _start_music()
    mouse.visible = True

    menu = Entity(parent=camera.ui)
    # decorative spinning UFO behind the title
    deco = Entity(parent=menu, model="sphere", color=color.hsv(195, 0.5, 0.9),
                  scale=(0.5, 0.12, 0.5), position=(0, 0.12, 0), rotation_z=10)
    deco.animate_rotation((0, 360, 10), duration=6, loop=True)

    Text("TANK  vs  ALIENS", parent=menu, origin=(0, 0), position=(0, 0.28),
         scale=3.2, color=color.lime)
    Text("3D", parent=menu, origin=(0, 0), position=(0, 0.15), scale=2.0,
         color=color.yellow)
    Text("Defend Earth. Blast the saucers and the alien horde.",
         parent=menu, origin=(0, 0), position=(0, 0.04), scale=1.0,
         color=color.light_gray)

    Button("START  GAME", parent=menu, scale=(0.32, 0.09), position=(0, -0.10),
           color=color.lime, text_color=color.black, highlight_color=color.yellow,
           on_click=start_game)
    Button("QUIT", parent=menu, scale=(0.32, 0.09), position=(0, -0.24),
           color=color.red, highlight_color=color.orange, on_click=quit_game)

    Text("WASD move    Mouse aim    Left-Click fire",
         parent=menu, origin=(0, 0), position=(0, -0.40), scale=0.85,
         color=color.gray)

    state["menu"] = menu


def _clear_menu():
    if state["menu"] is not None:
        destroy(state["menu"])
        state["menu"] = None


# ----------------------------------------------------------------- transitions
def start_game():
    play_sound("ui_click", volume=0.6)
    _clear_menu()
    if state["game"] is not None:
        state["game"].teardown()
        state["game"] = None
    state["game"] = Game(on_game_over=show_game_over)


def show_game_over(score):
    if state["game"] is not None:
        state["game"].teardown()
        state["game"] = None
    _clear_menu()
    mouse.visible = True

    menu = Entity(parent=camera.ui)
    Entity(parent=menu, model="quad", color=color.black, alpha=0.6,
           scale=(0.7, 0.6))
    Text("GAME OVER", parent=menu, origin=(0, 0), position=(0, 0.22),
         scale=3.0, color=color.red)
    Text(f"FINAL SCORE   {score}", parent=menu, origin=(0, 0), position=(0, 0.08),
         scale=1.6, color=color.yellow)

    Button("PLAY  AGAIN", parent=menu, scale=(0.32, 0.09), position=(0, -0.08),
           color=color.lime, text_color=color.black, highlight_color=color.yellow,
           on_click=start_game)
    Button("MAIN  MENU", parent=menu, scale=(0.32, 0.09), position=(0, -0.22),
           color=color.azure, highlight_color=color.cyan, on_click=show_main_menu)
    Button("QUIT", parent=menu, scale=(0.32, 0.09), position=(0, -0.36),
           color=color.red, highlight_color=color.orange, on_click=quit_game)

    state["menu"] = menu


def quit_game():
    play_sound("ui_click", volume=0.6)
    application.quit()


# ----------------------------------------------------------------------- input
def input(key):
    if key == "escape":
        if state["game"] is not None and state["game"].running:
            # abort the current run and go back to the menu
            state["game"].teardown()
            state["game"] = None
            show_main_menu()
        elif state["game"] is None:
            # already on a menu screen -> quit the app
            application.quit()


show_main_menu()
app.run()
