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
        self.enemy_soft_cap = 16
        self.rock_check_toggle = False
        self.enemy_grid_cell_size = 16.0
        self.chunk_size = 72.0
        self.chunk_radius = 1
        self.active_chunks = {}
        self.trees = []
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
        self.tank.ground_height_fn = self._terrain_height
        self.tank.obstacles = self.trees
        self._build_hud()
        self._setup_camera()
        mouse.visible = False
        mouse.locked = False

    # ------------------------------------------------------------------ setup
    def _build_world(self):
        self.sky = Sky()
        self.sky.color = color.hsv(26, 0.65, 0.95)

        # hide the old flat ground; rolling chunk tiles provide the visible terrain.
        self.ground = Entity(
            model="plane", scale=GROUND_SIZE, texture="white_cube",
            texture_scale=(GROUND_SIZE / 4, GROUND_SIZE / 4),
            color=color.hsv(45, 0.25, 0.55),
            visible=False,
        )
        # ... and a separate invisible plane at aim height for clean mouse aiming
        self.aim_plane = Entity(
            model="plane", scale=GROUND_SIZE, collider="box", visible=False, y=0.8
        )

        # seed nearby chunks; rocks stream in/out around the player over time.
        self._update_streaming_world(force=True)

    def _terrain_height(self, x, z):
        # lightweight deterministic rolling hills function.
        return (
            0.45 * math.sin(x * 0.030)
            + 0.35 * math.cos(z * 0.027)
            + 0.20 * math.sin((x + z) * 0.020)
        )

    def _chunk_key(self, x, z):
        return (int(math.floor(x / self.chunk_size)), int(math.floor(z / self.chunk_size)))

    def _spawn_chunk(self, cx, cz):
        rng = random.Random((cx * 73856093) ^ (cz * 19349663) ^ 0x1A2B3C)
        origin_x = cx * self.chunk_size
        origin_z = cz * self.chunk_size
        chunk_props = []
        chunk_rocks = []
        chunk_trees = []

        # rolling grass tiles: 2x2 tiles per chunk with tiny tilt from sampled slope.
        tile_size = self.chunk_size * 0.5
        for tx in (-0.25, 0.25):
            for tz in (-0.25, 0.25):
                cxw = origin_x + tx * self.chunk_size
                czw = origin_z + tz * self.chunk_size
                h = self._terrain_height(cxw, czw)
                sx = self._terrain_height(cxw + tile_size * 0.35, czw) - self._terrain_height(cxw - tile_size * 0.35, czw)
                sz = self._terrain_height(cxw, czw + tile_size * 0.35) - self._terrain_height(cxw, czw - tile_size * 0.35)
                tile = Entity(
                    model="cube",
                    color=color.hsv(110, 0.50, 0.52),
                    position=(cxw, h - 0.3, czw),
                    scale=(tile_size + 0.15, 0.65, tile_size + 0.15),
                    rotation=(clamp(-sz * 22, -8, 8), 0, clamp(sx * 22, -8, 8)),
                )
                chunk_props.append(tile)
                self.props.append(tile)

        # sparse decorative/ballistic rocks per chunk
        for _ in range(8):
            rx = origin_x + rng.uniform(-self.chunk_size * 0.45, self.chunk_size * 0.45)
            rz = origin_z + rng.uniform(-self.chunk_size * 0.45, self.chunk_size * 0.45)
            ry = self._terrain_height(rx, rz)
            rock = Entity(
                model="cube",
                color=color.hsv(30, 0.15, rng.uniform(0.4, 0.6)),
                position=(rx, ry + rng.uniform(-0.02, 0.18), rz),
                scale=rng.uniform(0.7, 1.8),
                rotation_y=rng.uniform(0, 360),
            )
            chunk_props.append(rock)
            self.props.append(rock)
            self.rocks.append(rock)
            chunk_rocks.append(rock)

        # sparse collidable trees (do not deal damage)
        for _ in range(rng.randint(1, 2)):
            tx = origin_x + rng.uniform(-self.chunk_size * 0.40, self.chunk_size * 0.40)
            tz = origin_z + rng.uniform(-self.chunk_size * 0.40, self.chunk_size * 0.40)
            ty = self._terrain_height(tx, tz)
            trunk_h = rng.uniform(1.8, 2.6)
            trunk_r = rng.uniform(0.36, 0.5)
            trunk = Entity(
                model="cube",
                color=color.hsv(30, 0.55, 0.30),
                position=(tx, ty + trunk_h * 0.5, tz),
                scale=(trunk_r, trunk_h, trunk_r),
                collider="box",
            )
            trunk.trunk_radius = trunk_r * 1.35
            leaves = Entity(
                parent=trunk,
                model="sphere",
                color=color.hsv(118, 0.68, rng.uniform(0.5, 0.68)),
                position=(0, trunk_h * 0.45, 0),
                scale=rng.uniform(1.6, 2.2),
            )
            chunk_props.append(trunk)
            chunk_props.append(leaves)
            self.props.append(trunk)
            self.props.append(leaves)
            self.trees.append(trunk)
            chunk_trees.append(trunk)

        self.active_chunks[(cx, cz)] = {
            "props": chunk_props,
            "rocks": chunk_rocks,
            "trees": chunk_trees,
        }

    def _update_streaming_world(self, force=False):
        # keep the invisible aim plane centered near the player
        center_x = self.tank.x if hasattr(self, "tank") else 0
        center_z = self.tank.z if hasattr(self, "tank") else 0
        self.aim_plane.x = center_x
        self.aim_plane.z = center_z

        if not hasattr(self, "tank"):
            return
        center = self._chunk_key(self.tank.x, self.tank.z)
        needed = set()
        for dx in range(-self.chunk_radius, self.chunk_radius + 1):
            for dz in range(-self.chunk_radius, self.chunk_radius + 1):
                needed.add((center[0] + dx, center[1] + dz))

        # spawn newly needed chunks
        for key in needed:
            if key not in self.active_chunks:
                self._spawn_chunk(key[0], key[1])

        # remove far chunks to keep entity count bounded
        if force:
            return
        stale = [key for key in self.active_chunks if key not in needed]
        for key in stale:
            chunk_data = self.active_chunks.pop(key)
            for r in chunk_data["rocks"]:
                if r in self.rocks:
                    self.rocks.remove(r)
            for t in chunk_data["trees"]:
                if t in self.trees:
                    self.trees.remove(t)
            for p in chunk_data["props"]:
                if p in self.rocks:
                    self.rocks.remove(p)
                if p in self.props:
                    self.props.remove(p)
                destroy(p)

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
        self._update_streaming_world()
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
            enemy_count = len(self.ufos) + len(self.aliens)
            if enemy_count >= self.enemy_soft_cap:
                # under heavy load, slow spawns instead of stacking more actors
                self.spawn_timer = 1.05
                return
            self.spawn_timer = max(0.75, 2.2 - self.elapsed * 0.02)
            self._spawn_enemy()

    def _spawn_enemy(self):
        ang = random.uniform(0, math.tau)
        dist = random.uniform(45, 70)
        px = self.tank.x + math.cos(ang) * dist
        pz = self.tank.z + math.sin(ang) * dist
        if random.random() < 0.45:
            self.ufos.append(UFO(position=(px, random.uniform(8, 12), pz), target=self.tank))
        else:
            gy = self._terrain_height(px, pz)
            alien = GroundAlien(position=(px, gy, pz), target=self.tank)
            alien.terrain_height_fn = self._terrain_height
            self.aliens.append(alien)

    def _grid_cell(self, p):
        s = self.enemy_grid_cell_size
        return (int(math.floor(p.x / s)), int(math.floor(p.z / s)))

    def _build_spatial_grid(self, enemies):
        grid = {}
        for e in enemies:
            if getattr(e, "dead", False):
                continue
            key = self._grid_cell(e.world_position)
            if key not in grid:
                grid[key] = []
            grid[key].append(e)
        return grid

    def _iter_nearby(self, grid, p):
        cx, cz = self._grid_cell(p)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                key = (cx + dx, cz + dz)
                if key in grid:
                    for e in grid[key]:
                        yield e

    # ------------------------------------------------------------- collisions
    def _collisions(self):
        ufo_grid = self._build_spatial_grid(self.ufos)
        alien_grid = self._build_spatial_grid(self.aliens)

        # player bullets vs enemies
        for b in self.player_bullets:
            if getattr(b, "dead", False):
                continue
            target = None
            for e in self._iter_nearby(ufo_grid, b.world_position):
                if not getattr(e, "dead", False) and distance(b, e) < 2.6:
                    target = e
                    break
            if target is None:
                for e in self._iter_nearby(alien_grid, b.world_position):
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
        # rocks are checked every other frame to cut worst-case per-frame cost.
        self.rock_check_toggle = not self.rock_check_toggle
        for b in self.player_bullets + self.enemy_bullets:
            if getattr(b, "dead", False):
                continue
            if self._bullet_world_hit(b, check_rocks=self.rock_check_toggle):
                pos = Vec3(b.world_position)
                b.dead = True
                destroy(b)
                Explosion(pos, scale=0.4, sound=False)

    def _bullet_world_hit(self, b, check_rocks=True):
        # slammed into the ground
        if b.y <= 0.12:
            return True
        if not check_rocks:
            return False
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
