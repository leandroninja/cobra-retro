import pygame
import sys
import json
import math
import random
import array
from collections import deque
from dataclasses import dataclass

# ── Constantes ────────────────────────────────────────────────────────────────
CELL     = 20
COLS     = 32
ROWS     = 28
GRID_W   = COLS * CELL   # 640
PANEL_H  = 60
SCREEN_W = GRID_W
SCREEN_H = ROWS * CELL + PANEL_H  # 620
FPS      = 60

# Paleta retrô verde fósforo
BG        = (0,   10,  0)
GRID_C    = (0,   28,  0)
SCANLINE  = (0,    0,  0)
HEAD_C    = (0,  255, 70)
BODY_TOP  = (0,  200, 50)
BODY_BOT  = (0,   80, 20)
FOOD_C    = (255, 60,  0)
PANEL_BG  = (0,   15,  0)
PANEL_BD  = (0,  180, 40)
GREEN     = (0,  255, 70)
DIM       = (0,  120, 30)

SPEED_INIT    = 8
SPEED_MAX     = 20
SCORE_FILE    = "highscore.json"

MENU, PLAYING, PAUSED, GAME_OVER = range(4)
SR = 44100  # sample rate


# ── Sons gerados por código ───────────────────────────────────────────────────
def _som_quadrado(freq, duracao, volume=0.3):
    n = int(SR * duracao)
    buf = array.array('h', [0] * (n * 2))
    period = SR / freq
    for i in range(n):
        val = int(32767 * volume * (1 if (i % period) < (period / 2) else -1))
        buf[2*i] = val
        buf[2*i+1] = val
    return pygame.mixer.Sound(buffer=buf)


def _som_sweep(f0, f1, duracao, volume=0.4):
    n = int(SR * duracao)
    buf = array.array('h', [0] * (n * 2))
    for i in range(n):
        t = i / SR
        freq = f0 + (f1 - f0) * (i / n)
        val = int(32767 * volume * math.sin(2 * math.pi * freq * t))
        buf[2*i] = val
        buf[2*i+1] = val
    return pygame.mixer.Sound(buffer=buf)


def _som_arpejo(notas, dur_nota, volume=0.35):
    n_total = int(SR * dur_nota * len(notas))
    buf = array.array('h', [0] * (n_total * 2))
    for idx, freq in enumerate(notas):
        inicio = int(idx * SR * dur_nota)
        fim    = int((idx + 1) * SR * dur_nota)
        for i in range(inicio, fim):
            t   = (i - inicio) / SR
            env = 1.0 - (i - inicio) / (fim - inicio)
            val = int(32767 * volume * env * math.sin(2 * math.pi * freq * t))
            buf[2*i] = val
            buf[2*i+1] = val
    return pygame.mixer.Sound(buffer=buf)


def _som_musica_loop(volume=0.18):
    """Chiptune 8-bit: onda quadrada com melodia, harmonia e baixo pulsante."""
    bpm  = 150
    beat = 60 / bpm
    h    = beat / 2
    q    = beat / 4

    def sq(freq, t):
        return 1.0 if (freq * t) % 1 < 0.5 else -1.0

    mel = [
        (659, q), (784, q), (880, h), (784, q), (659, q),
        (523, h), (0, h),
        (587, q), (659, q), (784, h), (659, q), (587, q),
        (523, beat), (0, beat),
        (880, q), (988, q), (1047, h), (880, q), (784, q),
        (659, h), (523, h),
        (784, q), (659, q), (587, q), (523, q),
        (659, beat), (0, beat),
    ]
    harm = [
        (523, q), (659, q), (784, h), (659, q), (523, q),
        (392, h), (0, h),
        (494, q), (523, q), (659, h), (523, q), (494, q),
        (392, beat), (0, beat),
        (784, q), (880, q), (988, h), (784, q), (659, q),
        (523, h), (392, h),
        (659, q), (523, q), (494, q), (392, q),
        (523, beat), (0, beat),
    ]
    bass_notas = [131, 131, 165, 165, 131, 131, 196, 196,
                  131, 131, 165, 165, 131, 131, 131, 131]
    bass_dur   = h

    total_mel  = sum(d for _, d in mel)
    total_bass = bass_dur * len(bass_notas)
    total      = max(total_mel, total_bass)
    n          = int(total * SR)
    buf        = array.array('h', [0] * (n * 2))

    for track, vol_mul in [(mel, 0.55), (harm, 0.35)]:
        pos = 0
        for freq, dur in track:
            samp = int(dur * SR)
            for i in range(samp):
                if freq > 0 and pos + i < n:
                    t   = i / SR
                    env = math.exp(-1.0 * t / dur)
                    v   = int(32767 * volume * vol_mul * env * sq(freq, t))
                    buf[2*(pos+i)]   = max(-32767, min(32767, buf[2*(pos+i)]   + v))
                    buf[2*(pos+i)+1] = max(-32767, min(32767, buf[2*(pos+i)+1] + v))
            pos += samp

    pos = 0
    for freq in bass_notas:
        samp = int(bass_dur * SR)
        for i in range(samp):
            if pos + i < n:
                t   = i / SR
                env = 0.4 + 0.6 * math.exp(-6 * t / bass_dur)
                v   = int(32767 * volume * 0.45 * env * sq(freq, t))
                buf[2*(pos+i)]   = max(-32767, min(32767, buf[2*(pos+i)]   + v))
                buf[2*(pos+i)+1] = max(-32767, min(32767, buf[2*(pos+i)+1] + v))
        pos += samp

    return pygame.mixer.Sound(buffer=buf)


# ── Utilidades ────────────────────────────────────────────────────────────────
@dataclass
class Particle:
    x: float; y: float
    vx: float; vy: float
    life: float
    color: tuple


def lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def spawn_particles(buf, gx, gy, color, n=12):
    cx = gx * CELL + CELL // 2
    cy = gy * CELL + CELL // 2
    for _ in range(n):
        ang = random.uniform(0, 2 * math.pi)
        spd = random.uniform(1.0, 3.5)
        buf.append(Particle(cx, cy, math.cos(ang)*spd, math.sin(ang)*spd, 1.0, color))


def draw_text(surf, text, font, color, x, y, center=False):
    img = font.render(text, True, color)
    surf.blit(img, (x - img.get_width()//2 if center else x, y))


def load_highscore():
    try:
        with open(SCORE_FILE) as f:
            return json.load(f).get("highscore", 0)
    except Exception:
        return 0


def save_highscore(score):
    try:
        with open(SCORE_FILE, "w") as f:
            json.dump({"highscore": score}, f)
    except Exception:
        pass


# ── Comida ────────────────────────────────────────────────────────────────────
class Food:
    def __init__(self, occupied):
        self.pulse = 0.0
        self.respawn(occupied)

    def respawn(self, occupied):
        while True:
            pos = (random.randint(0, COLS-1), random.randint(0, ROWS-1))
            if pos not in occupied:
                self.pos = pos
                self.pulse = 0.0
                break

    def update(self, dt):
        self.pulse += dt * 0.005

    def draw(self, surf):
        cx = self.pos[0] * CELL + CELL // 2
        cy = self.pos[1] * CELL + CELL // 2
        r  = max(4, int(CELL//2 - 2 + 2*abs(math.sin(self.pulse))))
        # Cruz pixel-art estilo retro
        pygame.draw.rect(surf, FOOD_C, (cx - r//2, cy - r, r, r*2))
        pygame.draw.rect(surf, FOOD_C, (cx - r, cy - r//2, r*2, r))


# ── Cobra ─────────────────────────────────────────────────────────────────────
def draw_snake(surf, segments, direction):
    n = len(segments)
    for i, (gx, gy) in enumerate(segments):
        t     = i / max(1, n-1)
        color = lerp_color(BODY_TOP, BODY_BOT, t) if i > 0 else HEAD_C
        rect  = pygame.Rect(gx*CELL+1, gy*CELL+1, CELL-2, CELL-2)
        pygame.draw.rect(surf, color, rect, border_radius=3)
        if i == 0:
            eye_map = {
                (1, 0):  [(5,-3),(5, 3)],
                (-1,0):  [(-5,-3),(-5,3)],
                (0,-1):  [(-3,-5),(3,-5)],
                (0, 1):  [(-3, 5),(3, 5)],
            }
            ecx = gx*CELL + CELL//2
            ecy = gy*CELL + CELL//2
            for ex, ey in eye_map.get(direction, [(3,-3),(3,3)]):
                pygame.draw.circle(surf, BG, (ecx+ex, ecy+ey), 2)


# ── Painel ────────────────────────────────────────────────────────────────────
def draw_panel(surf, fonts, score, highscore, level):
    py = ROWS * CELL
    surf.fill(PANEL_BG, (0, py, SCREEN_W, PANEL_H))
    pygame.draw.line(surf, PANEL_BD, (0, py), (SCREEN_W, py), 2)
    f_lg, f_md, f_sm = fonts
    pad = 24
    draw_text(surf, "PONTOS",        f_sm, DIM,    pad,          py+8)
    draw_text(surf, str(score),      f_lg, GREEN,  pad,          py+24)
    draw_text(surf, "RECORDE",       f_sm, DIM,    SCREEN_W//2 - 40, py+8)
    draw_text(surf, str(highscore),  f_lg, HEAD_C, SCREEN_W//2 - 40, py+24)
    draw_text(surf, "NIVEL",         f_sm, DIM,    SCREEN_W - 90, py+8)
    draw_text(surf, str(level),      f_lg, GREEN,  SCREEN_W - 90, py+24)


# ── Efeito scanlines ──────────────────────────────────────────────────────────
def draw_scanlines(surf):
    for y in range(0, SCREEN_H, 4):
        pygame.draw.line(surf, (0, 0, 0), (0, y), (SCREEN_W, y))


# ── Jogo ──────────────────────────────────────────────────────────────────────
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Cobra Retrô")
        self.fonts = (
            pygame.font.SysFont("consolas", 22, bold=True),
            pygame.font.SysFont("consolas", 14),
            pygame.font.SysFont("consolas", 11),
        )
        self.clock     = pygame.time.Clock()
        self.highscore = load_highscore()
        self._init_audio()
        self._build_bg()
        self._init_menu_snake()
        self.scanline_surf = self._make_scanlines()
        self.state = MENU
        self._new_game()

    def _init_audio(self):
        try:
            pygame.mixer.init(frequency=SR, size=-16, channels=2, buffer=512)
            self.sfx_comer   = _som_quadrado(880, 0.07, 0.35)
            self.sfx_nivel   = _som_arpejo([330, 392, 494, 659], 0.09, 0.35)
            self.sfx_morte   = _som_sweep(400, 60, 0.5, 0.45)
            self.sfx_inicio  = _som_arpejo([262, 330, 392, 523], 0.08, 0.3)
            self.musica      = _som_musica_loop(0.18)
            self.musica.play(-1)
        except Exception:
            self.sfx_comer = self.sfx_nivel = self.sfx_morte = self.sfx_inicio = self.musica = None

    def _play(self, sfx):
        if sfx:
            sfx.play()

    def _build_bg(self):
        self.bg_surf = pygame.Surface((SCREEN_W, ROWS*CELL))
        self.bg_surf.fill(BG)
        for c in range(COLS+1):
            pygame.draw.line(self.bg_surf, GRID_C, (c*CELL,0),(c*CELL,ROWS*CELL))
        for r in range(ROWS+1):
            pygame.draw.line(self.bg_surf, GRID_C, (0,r*CELL),(GRID_W,r*CELL))

    def _make_scanlines(self):
        s = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        for y in range(0, SCREEN_H, 4):
            pygame.draw.line(s, (0,0,0,60), (0,y),(SCREEN_W,y))
        return s

    def _init_menu_snake(self):
        path = []
        for x in range(COLS):              path.append((x, 0))
        for y in range(1, ROWS):           path.append((COLS-1, y))
        for x in range(COLS-2, -1, -1):   path.append((x, ROWS-1))
        for y in range(ROWS-2, 0, -1):    path.append((0, y))
        self.menu_path  = path
        self.menu_idx   = 0
        self.menu_snake = deque(maxlen=16)
        self.menu_timer = 0

    def _new_game(self):
        cx, cy          = COLS//2, ROWS//2
        self.snake      = deque([(cx,cy),(cx-1,cy),(cx-2,cy)])
        self.direction  = (1, 0)
        self.next_dir   = (1, 0)
        self.score      = 0
        self.level      = 1
        self.speed      = SPEED_INIT
        self.move_timer = 0
        self.particles  = []
        self.flash      = 0
        self.food       = Food(set(self.snake))

    def run(self):
        while True:
            dt = self.clock.tick(FPS)
            self._events()
            self._update(dt)
            self._draw()

    def _events(self):
        DIR_KEYS = {
            pygame.K_UP:    (0,-1), pygame.K_w: (0,-1),
            pygame.K_DOWN:  (0, 1), pygame.K_s: (0, 1),
            pygame.K_LEFT:  (-1,0), pygame.K_a: (-1,0),
            pygame.K_RIGHT: (1, 0), pygame.K_d: (1, 0),
        }
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                save_highscore(self.highscore); pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                k = event.key
                if k == pygame.K_ESCAPE:
                    save_highscore(self.highscore); pygame.quit(); sys.exit()
                if self.state == MENU and k == pygame.K_RETURN:
                    self._new_game(); self.state = PLAYING; self._play(self.sfx_inicio)
                elif self.state == PLAYING and k == pygame.K_p:
                    self.state = PAUSED
                elif self.state == PAUSED and k == pygame.K_p:
                    self.state = PLAYING
                elif self.state == GAME_OVER and k == pygame.K_RETURN:
                    self._new_game(); self.state = PLAYING; self._play(self.sfx_inicio)
                if self.state == PLAYING and k in DIR_KEYS:
                    nd = DIR_KEYS[k]
                    if nd[0]+self.direction[0] != 0 or nd[1]+self.direction[1] != 0:
                        self.next_dir = nd

    def _update(self, dt):
        alive = []
        for p in self.particles:
            p.x += p.vx; p.y += p.vy; p.vy += 0.06; p.life -= dt*0.002
            if p.life > 0: alive.append(p)
        self.particles = alive

        if self.flash > 0:
            self.flash = max(0, self.flash - dt)

        if self.state == MENU:
            self.menu_timer += dt
            if self.menu_timer >= 90:
                self.menu_timer = 0
                self.menu_idx   = (self.menu_idx+1) % len(self.menu_path)
                self.menu_snake.appendleft(self.menu_path[self.menu_idx])
            self.food.update(dt)
            return

        if self.state != PLAYING:
            return

        self.food.update(dt)
        self.move_timer += dt
        if self.move_timer < 1000 // self.speed:
            return
        self.move_timer = 0

        self.direction = self.next_dir
        hx, hy = self.snake[0]
        nx = hx + self.direction[0]
        ny = hy + self.direction[1]

        # Colisão com parede
        if nx < 0 or nx >= COLS or ny < 0 or ny >= ROWS:
            self._die(hx, hy); return

        # Colisão com corpo
        if (nx, ny) in self.snake:
            self._die(hx, hy); return

        self.snake.appendleft((nx, ny))

        if (nx, ny) == self.food.pos:
            nivel_antes   = self.level
            self.score   += 1
            self.level    = self.score // 5 + 1
            self.speed    = min(SPEED_INIT + self.level - 1, SPEED_MAX)
            if self.score > self.highscore:
                self.highscore = self.score
            spawn_particles(self.particles, nx, ny, FOOD_C)
            self.food.respawn(set(self.snake))
            if self.level > nivel_antes:
                self._play(self.sfx_nivel)
            else:
                self._play(self.sfx_comer)
        else:
            self.snake.pop()

    def _die(self, hx, hy):
        self.flash = 400
        spawn_particles(self.particles, hx, hy, HEAD_C, 20)
        if self.score > self.highscore:
            self.highscore = self.score
            save_highscore(self.highscore)
        self._play(self.sfx_morte)
        self.state = GAME_OVER

    def _draw(self):
        self.screen.blit(self.bg_surf, (0, 0))

        if self.state == MENU:
            n = len(self.menu_snake)
            for i, (gx, gy) in enumerate(self.menu_snake):
                t     = i / max(1, n-1)
                color = lerp_color(BODY_TOP, BODY_BOT, t) if i>0 else HEAD_C
                pygame.draw.rect(self.screen, color,
                                 (gx*CELL+1, gy*CELL+1, CELL-2, CELL-2), border_radius=3)
        else:
            draw_snake(self.screen, self.snake, self.direction)

        self.food.draw(self.screen)

        for p in self.particles:
            r = max(1, int(p.life*4))
            try:
                ps = pygame.Surface((r*2,r*2), pygame.SRCALPHA)
                pygame.draw.circle(ps, (*p.color, int(p.life*200)), (r,r), r)
                self.screen.blit(ps, (int(p.x)-r, int(p.y)-r))
            except Exception:
                pass

        if self.flash > 0:
            fs = pygame.Surface((GRID_W, ROWS*CELL), pygame.SRCALPHA)
            fs.fill((0, 255, 70, int(self.flash/400*80)))
            self.screen.blit(fs, (0, 0))

        # Scanlines retrô
        self.screen.blit(self.scanline_surf, (0, 0))

        draw_panel(self.screen, self.fonts, self.score, self.highscore, self.level)

        t_ms  = pygame.time.get_ticks()
        f_lg, f_md, f_sm = self.fonts
        mid   = SCREEN_W // 2

        if self.state == MENU:
            pulse = abs((t_ms % 1600) / 800.0 - 1.0)
            tc    = (0, int(180 + 75*pulse), int(50 + 20*pulse))
            draw_text(self.screen, "COBRA  RETRO",   f_lg, tc,    mid, 120, center=True)
            draw_text(self.screen, "Criada no celular, aperfeicoada aqui!", f_sm, DIM, mid, 180, center=True)
            if (t_ms // 500) % 2 == 0:
                draw_text(self.screen, "ENTER para jogar", f_md, GREEN, mid, 280, center=True)
            draw_text(self.screen, "Cuidado com as paredes!", f_sm, DIM, mid, 340, center=True)
        elif self.state == PAUSED:
            self._draw_overlay("PAUSADO", "P para continuar", mid, f_lg, f_md)
        elif self.state == GAME_OVER:
            self._draw_overlay("GAME  OVER", "ENTER para reiniciar", mid, f_lg, f_md)

        pygame.display.flip()

    def _draw_overlay(self, title, subtitle, mid, f_lg, f_md):
        ov = pygame.Surface((GRID_W, ROWS*CELL), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 170))
        self.screen.blit(ov, (0, 0))
        draw_text(self.screen, title,    f_lg, GREEN, mid, ROWS*CELL//2 - 40, center=True)
        draw_text(self.screen, subtitle, f_md, DIM,   mid, ROWS*CELL//2 + 10, center=True)


if __name__ == "__main__":
    Game().run()
