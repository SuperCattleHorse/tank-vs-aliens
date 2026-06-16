"""
Core gameplay for Tank vs Aliens 3D.

Game is an Ursina Entity, so its update()/input() run automatically every frame.
It owns the world, the player tank, all bullets and enemies, and drives spawning,
collisions, the HUD, the chase camera and win/lose handling.
"""
import math
import random

from ursina import (
    Entity, Sky, Text, camera, mouse, color, Vec3, time, destroy, invoke,
    lerp, distance, distance_xz, held_keys, clamp, window,
)

from entities import Tank, Bullet, UFO, GroundAlien, Explosion, ARENA_BOUND, GROUND_SIZE
from audio import play_sound


class Game(Entity):
    def __init__(self, on_game_over=None):
        super().__init__()
        self.on_game_over = on_game_over
        self.running = True
        self.score = 0
        self.elapsed = 0.0
        self.fire_cd = 0.0
        self.fire_interval = 0.22
        self.spawn_timer = 1.5

        self.props = []
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

        # scattered rocks for depth / reference
        for _ in range(45):
            self.props.append(Entity(
                model="cube", color=color.hsv(30, 0.15, random.uniform(0.4, 0.6)),
                position=(random.uniform(-ARENA_BOUND, ARENA_BOUND),
                          random.uniform(-0.1, 0.4),
                          random.uniform(-ARENA_BOUND, ARENA_BOUND)),
                scale=random.uniform(0.6, 1.7), rotation_y=random.uniform(0, 360)))

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
        Text("WASD move    Mouse aim    Left-Click fire    Esc menu",
             parent=self.hud, position=(0, -0.47), origin=(0, 0), scale=0.8,
             color=color.light_gray)
        self.crosshair = Text("+", parent=camera.ui, origin=(0, 0), scale=2.2,
                              color=color.yellow)

    def _setup_camera(self):
        # a slightly lower, pulled-back angle so flying saucers stay in view
        self.cam_height = 20
        self.cam_back = 21
        self.cam_pitch = 44
        camera.orthographic = False
        camera.fov = 60
        camera.position = (0, self.cam_height, -self.cam_back)
        camera.rotation = (self.cam_pitch, 0, 0)

    # ----------------------------------------------------------------- update
    def update(self):
        if not self.running:
            return
        self.elapsed += time.dt
        self._handle_fire()
        self._spawn()
        self._collisions()
        self._cleanup_lists()
        self._update_hud()
        self._update_camera()

    def _update_camera(self):
        target = Vec3(self.tank.x, self.cam_height, self.tank.z - self.cam_back)
        camera.position = lerp(camera.position, target, min(1, 6 * time.dt))
        camera.rotation = (self.cam_pitch, 0, 0)

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
        mouse.visible = True
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
