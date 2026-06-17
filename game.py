"""
Core gameplay for Tank vs Aliens 3D.

Game is an Ursina Entity, so its update()/input() run automatically every frame.
It owns the world, the player tank, all bullets and enemies, and drives spawning,
collisions, the HUD, the chase camera and win/lose handling.
"""
import math
import random

from ursina import (
    Entity, Sky, Text, Button, camera, mouse, color, Vec3, time, destroy, invoke,
    lerp, distance, distance_xz, held_keys, clamp, window, application,
)
from ursina.prefabs.slider import Slider

from entities import Tank, Bullet, UFO, GroundAlien, Explosion, ARENA_BOUND, GROUND_SIZE
from audio import play_sound


class Game(Entity):
    def __init__(self, on_game_over=None, on_exit=None):
        super().__init__()
        # keep receiving input (Esc) even while the game is paused
        self.ignore_paused = True
        self.on_game_over = on_game_over
        self.on_exit = on_exit
        self.running = True
        self.paused = False
        self.pause_menu = None
        self.score = 0
        self.elapsed = 0.0
        self.fire_cd = 0.0
        self.fire_interval = 0.22
        self.spawn_timer = 1.5
        # camera control: A/D yaw, mouse Y for pitch, settings slider adjusts sensitivity
        self.cam_yaw = 0           # current yaw offset from tank heading
        self.target_cam_yaw = 0    # target yaw for smooth lerp transition
        self.cam_pitch_offset = 0  # current pitch offset from base pitch
        self.mouse_look_sensitivity = 0.5  # default 0-1 scale, adjustable in settings

        self.props = []
        self.rocks = []
        self.player_bullets = []
        self.enemy_bullets = []
        self.ufos = []
        self.aliens = []

        self._build_world()
        self.tank = Tank(position=(0, 0, 0))
        self._build_hud()
        self._setup_camera()
        mouse.visible = False
        mouse.locked = False

    # ------------------------------------------------------------------ setup
    def _build_world(self):
        self.sky = Sky()
        self.sky.color = color.hsv(210, 0.30, 0.95)

        # visible ground (no collider) ...
        self.ground = Entity(
            model="plane", scale=GROUND_SIZE, texture="white_cube",
            texture_scale=(GROUND_SIZE / 4, GROUND_SIZE / 4),
            color=color.hsv(45, 0.25, 0.55),
        )
        # ... and a separate invisible plane at aim height for clean mouse aiming
        self.aim_plane = Entity(
            model="plane", scale=GROUND_SIZE, collider="box", visible=False, y=0.8
        )

        # boundary walls (visual only)
        b = ARENA_BOUND + 3
        for px, pz, sx, sz in [(0, b, 2 * b, 2), (0, -b, 2 * b, 2),
                               (b, 0, 2, 2 * b), (-b, 0, 2, 2 * b)]:
            self.props.append(Entity(
                model="cube", color=color.hsv(30, 0.30, 0.35),
                scale=(sx, 3, sz), position=(px, 1.5, pz)))

        # scattered rocks for depth / reference -- they also stop & detonate shells
        for _ in range(45):
            rock = Entity(
                model="cube", color=color.hsv(30, 0.15, random.uniform(0.4, 0.6)),
                position=(random.uniform(-ARENA_BOUND, ARENA_BOUND),
                          random.uniform(-0.1, 0.4),
                          random.uniform(-ARENA_BOUND, ARENA_BOUND)),
                scale=random.uniform(0.6, 1.7), rotation_y=random.uniform(0, 360))
            self.props.append(rock)
            self.rocks.append(rock)

    def _build_hud(self):
        self.hud = Entity(parent=camera.ui)
        # HP bar
        Entity(parent=self.hud, model="quad", color=color.black, alpha=0.6,
               scale=(0.42, 0.045), position=(-0.86, 0.46), origin=(-0.5, 0))
        self.hp_bar = Entity(parent=self.hud, model="quad", color=color.lime,
                             scale=(0.42, 0.045), position=(-0.86, 0.46), origin=(-0.5, 0))
        Text("HP", parent=self.hud, position=(-0.86, 0.49), scale=0.9, color=color.white)
        self.score_text = Text("SCORE  0", parent=self.hud, position=(0.86, 0.47),
                               origin=(1, 0), scale=1.2, color=color.yellow)
        self.info_text = Text("", parent=self.hud, position=(0, 0.47), origin=(0, 0),
                              scale=1.0, color=color.white)
        Text("WASD move    Mouse aim    Left-Click fire    Esc pause",
             parent=self.hud, position=(0, -0.47), origin=(0, 0), scale=0.8,
             color=color.light_gray)
        self.crosshair = Text("+", parent=camera.ui, origin=(0, 0), scale=2.2,
                              color=color.yellow)

    def _setup_camera(self):
        # stable third-person chase camera: fixed pitch + tank-relative yaw
        self.cam_height = 9.0          # how far above the tank the camera sits
        self.cam_back = 17.0           # how far behind the tank it trails
        self.cam_pitch = 18            # fixed pitch avoids look_at roll/flip artifacts
        self.cam_lerp = 5.0            # follow smoothing (higher = snappier)
        camera.orthographic = False
        camera.fov = 70
        # start already parked behind the tank's initial heading (+Z forward)
        camera.position = (0, self.cam_height, -self.cam_back)
        camera.rotation = (self.cam_pitch, 0, 0)
        self.prev_mouse_y = mouse.y

    # ------------------------------------------------------------------ pause
    def input(self, key):
        # Esc toggles pause instead of bailing straight out to the menu
        if key == "escape" and self.running:
            self.toggle_pause()

    def toggle_pause(self):
        if not self.running:
            return
        self.paused = not self.paused
        application.paused = self.paused
        mouse.visible = self.paused
        mouse.locked = False
        if self.paused:
            self._build_pause_menu()
        elif self.pause_menu is not None:
            destroy(self.pause_menu)
            self.pause_menu = None

    def _build_pause_menu(self):
        # ignore_paused=True keeps these widgets interactive while the world is frozen
        self.pause_menu = Entity(parent=camera.ui, ignore_paused=True)
        Entity(parent=self.pause_menu, model="quad", color=color.hsv(220, 0.45, 0.06),
               alpha=0.85, scale=(0.66, 0.82), ignore_paused=True)
        Text("PAUSED", parent=self.pause_menu, origin=(0, 0), position=(0, 0.26),
             scale=2.8, color=color.hsv(45, 0.85, 1.0))
        Text("The horde will wait... for now.", parent=self.pause_menu, origin=(0, 0),
             position=(0, 0.15), scale=1.0, color=color.hsv(195, 0.30, 0.92))
        Button("RESUME", parent=self.pause_menu, scale=(0.34, 0.09), position=(0, 0.0),
               color=color.hsv(140, 0.55, 0.6), text_color=color.black,
               highlight_color=color.hsv(140, 0.55, 0.78), ignore_paused=True,
               on_click=self.toggle_pause)
        Button("MAIN MENU", parent=self.pause_menu, scale=(0.34, 0.09), position=(0, -0.13),
               color=color.hsv(210, 0.55, 0.68), text_color=color.white,
               highlight_color=color.hsv(200, 0.6, 0.85), ignore_paused=True,
               on_click=self.exit_to_menu)
        Button("QUIT", parent=self.pause_menu, scale=(0.34, 0.09), position=(0, -0.26),
               color=color.hsv(5, 0.7, 0.6), text_color=color.white,
               highlight_color=color.hsv(20, 0.85, 0.75), ignore_paused=True,
               on_click=application.quit)
        
        # mouse look sensitivity control
        Text("Sensitivity", parent=self.pause_menu, origin=(0, 0), position=(0, -0.36),
             scale=0.8, color=color.light_gray)
        self.sens_slider = Slider(
            parent=self.pause_menu, min=0, max=1, default=self.mouse_look_sensitivity,
            position=(0, -0.44), scale=(0.32, 0.05), ignore_paused=True,
            on_change=self._update_sensitivity
        )

    def _update_sensitivity(self, value):
        self.mouse_look_sensitivity = clamp(value, 0, 1)

    def exit_to_menu(self):
        # leave the paused run and hand control back to the main menu
        application.paused = False
        self.paused = False
        if self.pause_menu is not None:
            destroy(self.pause_menu)
            self.pause_menu = None
        if self.on_exit is not None:
            invoke(self.on_exit, delay=0.02)

    # ----------------------------------------------------------------- update
    def update(self):
        if self.paused or not self.running:
            return
        self.elapsed += time.dt
        self._handle_fire()
        self._spawn()
        self._collisions()
        self._cleanup_lists()
        self._update_hud()
        self._update_camera()

    def _update_camera(self):
        # A/D (strafe keys) control yaw offset with smooth continuous rotation
        # only A/D keys affect camera yaw, continuously from -45 to +45 degrees
        a_input = held_keys["d"] - held_keys["a"]  # +1 right, -1 left, 0 neutral
        # accumulate yaw offset based on A/D, 3.75 deg/sec rotation speed (slower for precise control)
        self.cam_yaw += a_input * 3.75 * time.dt
        self.cam_yaw = clamp(self.cam_yaw, -45, 45)  # clamp to reasonable arc
        
        # mouse Y position changes pitch: lower mouse = look down, higher = look up (inverted from common FPS)
        mouse_delta_y = mouse.y - self.prev_mouse_y
        self.prev_mouse_y = mouse.y
        self.cam_pitch_offset -= mouse_delta_y * 80 * self.mouse_look_sensitivity  # inverted for intuitive aim
        self.cam_pitch_offset = clamp(self.cam_pitch_offset, -20, 20)
        
        # position trails behind tank at current heading + yaw offset
        rad = math.radians(self.tank.rotation_y + self.cam_yaw)
        forward = Vec3(math.sin(rad), 0, math.cos(rad))
        desired = (self.tank.world_position
                   + Vec3(0, self.cam_height, 0)
                   - forward * self.cam_back)
        camera.position = lerp(camera.position, desired, min(1, self.cam_lerp * time.dt))
        
        # rotation: base pitch + mouse offset, yaw = tank + A/D offset
        camera.rotation = (self.cam_pitch + self.cam_pitch_offset, 
                           self.tank.rotation_y + self.cam_yaw, 0)

    def _update_hud(self):
        self.hp_bar.scale_x = 0.42 * max(0, self.tank.hp) / self.tank.max_hp
        self.hp_bar.color = color.lime if self.tank.hp > 30 else color.red
        self.score_text.text = f"SCORE  {self.score}"
        self.info_text.text = f"TIME {int(self.elapsed)}s    ENEMIES {len(self.ufos) + len(self.aliens)}"
        self.crosshair.position = (mouse.x, mouse.y)
        # turn the crosshair red while locked onto an enemy under the cursor
        hovered = mouse.hovered_entity
        if hovered is not None and getattr(hovered, "is_enemy", False):
            self.crosshair.color = color.red
            self.crosshair.text = "X"
        else:
            self.crosshair.color = color.yellow
            self.crosshair.text = "+"

    # ------------------------------------------------------------------- fire
    def _handle_fire(self):
        self.fire_cd -= time.dt
        if self.tank.alive and mouse.left and self.fire_cd <= 0:
            self.fire()

    def fire(self):
        self.fire_cd = self.fire_interval
        pos = self.tank.muzzle_position
        # shoot at the exact same aim point used by the turret this frame
        target = getattr(self.tank, "current_aim_point", None)
        if target is not None:
            direction = (Vec3(target) - pos).normalized()
        else:
            direction = self.tank.aim_direction
        self.player_bullets.append(
            Bullet(pos, direction, speed=62, owner="player", col=color.yellow, scale=0.35))
        flash = Entity(model="sphere", color=color.orange, position=pos, scale=0.7)
        flash.animate_scale(0.01, duration=0.12)
        destroy(flash, delay=0.12)
        play_sound("shoot", volume=0.35)

    # ----------------------------------------------------------------- spawn
    def _spawn(self):
        self.spawn_timer -= time.dt
        if self.spawn_timer <= 0:
            self.spawn_timer = max(0.55, 2.2 - self.elapsed * 0.02)
            self._spawn_enemy()

    def _spawn_enemy(self):
        ang = random.uniform(0, math.tau)
        dist = random.uniform(45, 70)
        px = clamp(self.tank.x + math.cos(ang) * dist, -ARENA_BOUND, ARENA_BOUND)
        pz = clamp(self.tank.z + math.sin(ang) * dist, -ARENA_BOUND, ARENA_BOUND)
        if random.random() < 0.45:
            self.ufos.append(UFO(position=(px, random.uniform(8, 12), pz), target=self.tank))
        else:
            self.aliens.append(GroundAlien(position=(px, 0, pz), target=self.tank))

    # ------------------------------------------------------------- collisions
    def _collisions(self):
        # player bullets vs enemies
        for b in self.player_bullets:
            if getattr(b, "dead", False):
                continue
            target = None
            for e in self.ufos:
                if not getattr(e, "dead", False) and distance(b, e) < 2.6:
                    target = e
                    break
            if target is None:
                for e in self.aliens:
                    if (not getattr(e, "dead", False)
                            and distance_xz(b, e) < 1.5 and abs(b.y - e.y) < 2.6):
                        target = e
                        break
            if target is not None:
                b.dead = True
                destroy(b)
                target.hp -= 1
                if target.hp <= 0:
                    self._kill_enemy(target)
                else:
                    play_sound("hit", volume=0.5)
                    Explosion(target.world_position, scale=0.5, sound=False)

        # enemy bullets vs tank
        for b in self.enemy_bullets:
            if getattr(b, "dead", False):
                continue
            if distance_xz(b, self.tank) < 1.9 and abs(b.y - 0.9) < 2.6:
                pos = Vec3(b.world_position)   # capture before destroy
                b.dead = True
                destroy(b)
                Explosion(pos, scale=0.5, sound=False)
                self._damage_player(10)

        # ground aliens reaching the tank
        for a in self.aliens:
            if getattr(a, "dead", False):
                continue
            if distance_xz(a, self.tank) < 2.0:
                self._kill_enemy(a, give_score=False)
                self._damage_player(14)

        # UFOs shooting at the tank
        for u in self.ufos:
            if getattr(u, "dead", False):
                continue
            u.fire_timer -= time.dt
            if u.fire_timer <= 0:
                u.fire_timer = random.uniform(2.0, 3.8)
                self._ufo_fire(u)

        # any bullet that slams into a wall, the ground or a rock detonates and
        # is removed, so shells never sail on past whatever they struck
        for b in self.player_bullets + self.enemy_bullets:
            if getattr(b, "dead", False):
                continue
            if self._bullet_world_hit(b):
                pos = Vec3(b.world_position)
                b.dead = True
                destroy(b)
                Explosion(pos, scale=0.4, sound=False)

    def _bullet_world_hit(self, b):
        # reached an arena wall (or flew off the field)
        if abs(b.x) > ARENA_BOUND + 2 or abs(b.z) > ARENA_BOUND + 2:
            return True
        # slammed into the ground
        if b.y <= 0.12:
            return True
        # struck one of the scattered rocks
        for r in self.rocks:
            half = r.scale_x * 0.5
            if distance_xz(b, r) < half + 0.25 and b.y < r.world_y + r.scale_y * 0.5 + 0.2:
                return True
        return False

    def _ufo_fire(self, u):
        direction = (self.tank.world_position + Vec3(0, 0.9, 0)) - u.world_position
        self.enemy_bullets.append(
            Bullet(u.world_position, direction, speed=24, owner="enemy",
                   col=color.red, scale=0.45, lifetime=4))
        play_sound("shoot", volume=0.2)

    def _kill_enemy(self, e, give_score=True):
        e.dead = True
        if give_score:
            self.score += getattr(e, "score", 50)
        Explosion(e.world_position, scale=1.0, volume=0.5)
        destroy(e)

    def _damage_player(self, amount):
        if not self.tank.alive:
            return
        self.tank.take_damage(amount)
        play_sound("player_hurt", volume=0.5)
        if not self.tank.alive:
            self._game_over()

    def _cleanup_lists(self):
        self.player_bullets = [b for b in self.player_bullets if not getattr(b, "dead", False)]
        self.enemy_bullets = [b for b in self.enemy_bullets if not getattr(b, "dead", False)]
        self.ufos = [e for e in self.ufos if not getattr(e, "dead", False)]
        self.aliens = [e for e in self.aliens if not getattr(e, "dead", False)]

    # --------------------------------------------------------------- game over
    def _game_over(self):
        if not self.running:
            return
        self.running = False
        play_sound("game_over", volume=0.7)
        Explosion(self.tank.world_position, scale=3.0, volume=0.7)
        self.tank.enabled = False
        self.tank.turret.enabled = False
        invoke(self._finish, delay=1.6)

    def _finish(self):
        if self.on_game_over:
            self.on_game_over(self.score)

    # --------------------------------------------------------------- teardown
    def teardown(self):
        self.running = False
        self.paused = False
        application.paused = False
        mouse.visible = True
        if self.pause_menu is not None:
            destroy(self.pause_menu)
            self.pause_menu = None
        for group in (self.player_bullets, self.enemy_bullets, self.ufos, self.aliens):
            for e in group:
                destroy(e)
        for p in self.props:
            destroy(p)
        destroy(self.tank.turret)
        destroy(self.tank)
        destroy(self.ground)
        destroy(self.aim_plane)
        destroy(self.sky)
        destroy(self.crosshair)
        destroy(self.hud)
        destroy(self)
