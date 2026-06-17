"""
Game entities for Tank vs Aliens 3D.

All objects are built from Ursina primitive models (cube / sphere), so no
external 3D model files are needed. Each entity only handles its own visuals
and self-movement; collisions, damage and spawning are orchestrated by game.py.
"""
import math
import random

from ursina import (
    Entity, Vec3, color, time, destroy, curve, mouse, held_keys, clamp, lerp,
)

from audio import play_sound

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
ARENA_BOUND = 88            # half-size of the playable square (ground is 200)
GROUND_SIZE = 200

ARMY_GREEN = color.hsv(85, 0.45, 0.50)
ARMY_GREEN_DARK = color.hsv(85, 0.50, 0.38)
TRACK_GRAY = color.hsv(0, 0, 0.22)
ALIEN_GREEN = color.hsv(105, 0.70, 0.75)
ALIEN_GREEN_DARK = color.hsv(105, 0.75, 0.45)
UFO_GRAY = color.hsv(210, 0.10, 0.80)
UFO_GLASS = color.hsv(195, 0.60, 0.95)


def face_y(entity, tx, tz):
    """Rotate entity around Y so its +Z (forward) points at world point (tx, tz)."""
    entity.rotation_y = math.degrees(math.atan2(tx - entity.world_x, tz - entity.world_z))


# ---------------------------------------------------------------------------
# Player tank
# ---------------------------------------------------------------------------
class Tank(Entity):
    """Player tank: WASD twin-stick movement, mouse-aimed turret."""

    def __init__(self, position=(0, 0, 0)):
        super().__init__(position=position)
        self.speed = 9
        self.max_hp = 100
        self.hp = self.max_hp
        self.alive = True
        self.ground_height_fn = None
        self.obstacles = []
        self.hover_offset = 0.02

        # --- hull (body) ---
        self.hull = Entity(parent=self, model="cube", color=ARMY_GREEN,
                           scale=(2.0, 0.7, 3.0), position=(0, 0.55, 0))
        # sloped front plate
        Entity(parent=self, model="cube", color=ARMY_GREEN_DARK,
               scale=(1.9, 0.5, 0.8), position=(0, 0.65, 1.4), rotation=(25, 0, 0))
        # tracks
        for side in (-1, 1):
            Entity(parent=self, model="cube", color=TRACK_GRAY,
                   scale=(0.5, 0.55, 3.3), position=(side * 1.02, 0.3, 0))

        # --- turret (independent world-space heading, follows tank position) ---
        self.turret = Entity(model="cube", color=ARMY_GREEN_DARK, scale=(1.3, 0.55, 1.5))
        Entity(parent=self.turret, model="sphere", color=ARMY_GREEN,
               scale=(1.0, 0.9, 1.0), position=(0, 0.2, -0.1))
        # cannon barrel points along turret +Z
        self.barrel = Entity(parent=self.turret, model="cube", color=TRACK_GRAY,
                             scale=(0.22, 0.22, 2.2), position=(0, 0.15, 1.2))
        self.turret_height = 1.15
        self.current_aim_point = self.world_position + Vec3(0, 0.8, 25)

    @property
    def muzzle_position(self):
        # muzzle position at barrel end, accounting for barrel elevation
        # this ensures bullet origin matches barrel direction
        # barrel length is 2.2, so tip is half-length from the barrel center
        barrel_tip = self.barrel.world_position + Vec3(self.barrel.forward).normalized() * 1.1
        return barrel_tip

    @property
    def aim_direction(self):
        # the barrel elevates toward the target so flying saucers stay hittable
        return Vec3(self.barrel.forward).normalized()

    def update(self):
        if not self.alive:
            return
        # --- tank-style controls ---
        # A/D rotate hull left/right; W/S move forward/back along current facing.
        turn_input = held_keys["d"] - held_keys["a"]
        self.rotation_y += turn_input * 110 * time.dt

        move_input = held_keys["w"] - held_keys["s"]
        if abs(move_input) > 0.01:
            rad = math.radians(self.rotation_y)
            forward = Vec3(math.sin(rad), 0, math.cos(rad))
            step = forward * move_input * self.speed * time.dt
            tentative = self.position + step
            if not self._would_hit_obstacle(tentative):
                self.position = tentative

        # follow rolling terrain and add a mild body tilt from local slope
        if self.ground_height_fn is not None:
            ground_y = self.ground_height_fn(self.x, self.z)
            self.y = lerp(self.y, ground_y + self.hover_offset, min(1, 7 * time.dt))

            sample = 1.6
            h_l = self.ground_height_fn(self.x - sample, self.z)
            h_r = self.ground_height_fn(self.x + sample, self.z)
            h_b = self.ground_height_fn(self.x, self.z - sample)
            h_f = self.ground_height_fn(self.x, self.z + sample)
            target_roll = clamp((h_l - h_r) * 14.0, -11, 11)
            target_pitch = clamp((h_b - h_f) * 14.0, -11, 11)
            self.rotation_z = lerp(self.rotation_z, target_roll, min(1, 8 * time.dt))
            self.rotation_x = lerp(self.rotation_x, target_pitch, min(1, 8 * time.dt))
        else:
            self.rotation_z = lerp(self.rotation_z, 0, min(1, 8 * time.dt))
            self.rotation_x = lerp(self.rotation_x, 0, min(1, 8 * time.dt))

        # turret sits flat on top of the hull: it only yaws (spins level) to
        # track the aim, while the barrel alone elevates -- so the turret never
        # looks tilted yet the cannon can still point up at flying saucers
        self.turret.position = self.world_position + Vec3(0, self.turret_height, 0)

        # lock on enemy root center instead of pick-volume surface point,
        # so crosshair lock and hit registration stay consistent.
        aim = None
        hovered = mouse.hovered_entity
        if hovered is not None and getattr(hovered, "is_enemy", False):
            # Prefer raycast hit point; it avoids stale-entity world_position lookups.
            if mouse.world_point is not None:
                aim = mouse.world_point
            else:
                enemy_root = hovered.parent if hovered.parent is not None else hovered
                y_offset = getattr(enemy_root, "aim_offset_y", 0.35)
                # hovered/pick can go stale right after destroy(); guard empty node paths.
                try:
                    if (enemy_root is not None
                            and getattr(enemy_root, "enabled", True)
                            and not enemy_root.is_empty()):
                        aim = enemy_root.world_position + Vec3(0, y_offset, 0)
                    else:
                        aim = None
                except Exception:
                    aim = None
        else:
            aim = mouse.world_point

        if aim is not None:
            self.current_aim_point = Vec3(aim)
            dx = aim.x - self.turret.world_x
            dz = aim.z - self.turret.world_z
            self.turret.rotation = (0, math.degrees(math.atan2(dx, dz)), 0)
            horizontal = math.sqrt(dx * dx + dz * dz)
            dy = aim.y - (self.turret.world_y + 0.15)
            elevation = math.degrees(math.atan2(dy, max(horizontal, 0.001)))
            # negative rotation_x raises the muzzle; allow steeper up-angle for close/high UFOs
            self.barrel.rotation_x = clamp(-elevation, -85, 15)

    def _would_hit_obstacle(self, p):
        for o in self.obstacles:
            if getattr(o, "disabled", False):
                continue
            r = getattr(o, "trunk_radius", 0.7)
            dx = p.x - o.x
            dz = p.z - o.z
            if dx * dx + dz * dz < (r + 1.0) * (r + 1.0):
                return True
        return False

    def take_damage(self, amount):
        if not self.alive:
            return
        self.hp = max(0, self.hp - amount)
        # quick red damage flash
        self.hull.blink(color.red, duration=0.25)
        if self.hp <= 0:
            self.alive = False

    def destroy_self(self):
        destroy(self.turret)
        destroy(self)


def _approach_angle(current, target, max_delta):
    """Move an angle (degrees) toward target by at most max_delta, shortest way."""
    diff = (target - current + 180) % 360 - 180
    if abs(diff) <= max_delta:
        return target
    return current + math.copysign(max_delta, diff)


# ---------------------------------------------------------------------------
# Bullets
# ---------------------------------------------------------------------------
class Bullet(Entity):
    """A projectile. owner is 'player' or 'enemy'."""

    def __init__(self, position, direction, speed=55, owner="player",
                 col=color.yellow, scale=0.35, lifetime=2.5):
        super().__init__(model="sphere", color=col, scale=scale, position=position)
        self.direction = Vec3(direction).normalized()
        self.speed = speed
        self.owner = owner
        self.lifetime = lifetime
        self.dead = False
        # soft glow halo
        Entity(parent=self, model="sphere", color=col, scale=1.8, alpha=0.30)

    def update(self):
        self.position += self.direction * self.speed * time.dt
        self.lifetime -= time.dt
        if self.lifetime <= 0:
            self.dead = True
            destroy(self)


# ---------------------------------------------------------------------------
# Explosion effect
# ---------------------------------------------------------------------------
class Explosion(Entity):
    def __init__(self, position, scale=1.0, sound=True, volume=0.5):
        super().__init__(position=position)
        flash = Entity(parent=self, model="sphere", color=color.orange, scale=0.6 * scale)
        flash.animate_scale(2.2 * scale, duration=0.22, curve=curve.out_expo)
        flash.fade_out(duration=0.24)

        core = Entity(parent=self, model="sphere", color=color.yellow, scale=0.3 * scale)
        core.animate_scale(1.3 * scale, duration=0.18, curve=curve.out_expo)
        core.fade_out(duration=0.22)

        # lower-cost shard count: large kills still look punchy, tiny impacts stay cheap
        if scale >= 1.0:
            shard_count = 4
        elif scale >= 0.5:
            shard_count = 2
        else:
            shard_count = 1

        for _ in range(shard_count):
            shard = Entity(parent=self, model="cube", color=color.orange, scale=0.22 * scale)
            d = Vec3(random.uniform(-1, 1), random.uniform(0.2, 1), random.uniform(-1, 1)).normalized()
            shard.animate_position(d * 2.0 * scale, duration=0.28, curve=curve.out_expo)
            shard.animate_rotation((random.uniform(0, 360),) * 3, duration=0.28)
            shard.fade_out(duration=0.28)

        if sound:
            play_sound("explosion", volume=volume)
        destroy(self, delay=0.4)


# ---------------------------------------------------------------------------
# Flying saucer (UFO)
# ---------------------------------------------------------------------------
class UFO(Entity):
    def __init__(self, position, target):
        super().__init__(position=position)
        self.target = target
        self.hp = 2
        self.speed = 4.5
        self.hover_radius = 16
        self.aim_offset_y = 0.35
        self.base_y = position[1]
        self.t = random.uniform(0, 6.28)
        self.fire_timer = random.uniform(1.5, 3.5)
        self.score = 150

        Entity(parent=self, model="sphere", color=UFO_GRAY, scale=(2.6, 0.5, 2.6))
        Entity(parent=self, model="sphere", color=UFO_GRAY, scale=(1.8, 0.35, 1.8), y=-0.15)
        Entity(parent=self, model="sphere", color=UFO_GLASS, scale=(1.2, 1.0, 1.2),
               y=0.35, alpha=0.85)
        # rotating underside lights
        self.lights = Entity(parent=self, y=-0.2)
        for i in range(6):
            a = i / 6 * math.tau
            Entity(parent=self.lights, model="sphere", color=color.lime, scale=0.22,
                   position=(math.cos(a) * 1.0, 0, math.sin(a) * 1.0))

        # invisible pick volume so the mouse can lock onto the saucer in the air
        pick = Entity(parent=self, model="sphere", collider="sphere",
                      scale=3.2, visible=False)
        pick.is_enemy = True

    def update(self):
        tx, tz = self.target.world_x, self.target.world_z
        to = Vec3(tx - self.x, 0, tz - self.z)
        dist = to.length()
        if dist > self.hover_radius:
            self.position += to.normalized() * self.speed * time.dt
        else:
            tangent = Vec3(-to.z, 0, to.x).normalized()
            self.position += tangent * self.speed * 0.7 * time.dt
        self.t += time.dt
        self.y = self.base_y + math.sin(self.t * 1.5) * 0.7
        self.lights.rotation_y += 90 * time.dt


# ---------------------------------------------------------------------------
# Ground alien soldier
# ---------------------------------------------------------------------------
class GroundAlien(Entity):
    def __init__(self, position, target):
        super().__init__(position=position)
        self.target = target
        self.hp = 1
        self.speed = random.uniform(2.2, 3.4)
        self.aim_offset_y = 1.1
        self.terrain_height_fn = None
        self.t = random.uniform(0, 6.28)
        self.score = 50
        self.attacked = False

        Entity(parent=self, model="sphere", color=ALIEN_GREEN,
               scale=(0.9, 1.2, 0.7), position=(0, 0.7, 0))
        head = Entity(parent=self, model="sphere", color=ALIEN_GREEN, scale=0.62, y=1.45)
        for sx in (-0.18, 0.18):
            Entity(parent=head, model="sphere", color=color.black, scale=0.32,
                   position=(sx, 0.05, 0.42))
            Entity(parent=head, model="sphere", color=color.red, scale=0.16,
                   position=(sx, 0.05, 0.52))
        # antenna
        Entity(parent=self, model="cube", color=ALIEN_GREEN_DARK,
               scale=(0.05, 0.4, 0.05), y=1.9)
        Entity(parent=self, model="sphere", color=color.red, scale=0.14, y=2.12)
        # arms
        for sx in (-0.62, 0.62):
            Entity(parent=self, model="cube", color=ALIEN_GREEN_DARK,
                   scale=(0.18, 0.6, 0.18), position=(sx, 0.8, 0))

        # invisible pick volume so the mouse can lock onto the alien
        pick = Entity(parent=self, model="cube", collider="box",
                      scale=(1.4, 2.4, 1.2), position=(0, 1.1, 0), visible=False)
        pick.is_enemy = True

    def update(self):
        tx, tz = self.target.world_x, self.target.world_z
        face_y(self, tx, tz)
        self.position += self.forward * self.speed * time.dt
        # little hopping walk
        self.t += time.dt * 9
        base = self.terrain_height_fn(self.x, self.z) if callable(self.terrain_height_fn) else 0
        self.y = base + abs(math.sin(self.t)) * 0.18
