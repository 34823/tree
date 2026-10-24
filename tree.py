#!/usr/bin/env python3
"""tree.py — процедурное дерево для /zen: полублоки 24-bit, рост, ветер, листопад, сезоны.

Запуск:  tree.py [--preset oak|sakura|birch|acacia|willow|pine] [--season auto|spring|summer|autumn|winter]
Мышь: зажал и провёл — срезал ветки и листву; просто водить — ничего. f — зажигалка (огонь по дереву, дождь тушит)
Клавиши: n новое · i бесконечный режим (новое случайное дерево за деревом) · p вид · s сезон · ↑↓ ветер · ←→ скорость роста · w погода · d время суток · q выход
Снизу панель кнопок (кликаются мышью и дублируют клавиши).
Каждое дерево растёт симуляцией (верхушки с запасом жизни, ветвление, тяга к свету, обход соседей) — свой seed, своя форма;
листья сидят на веточках и распускаются от них. Дерево растёт и толстеет со временем (возраст в ~/.cache/tree/state.json); срезанное отрастает от пня,
листья возвращаются светлыми; птицы, бабочки, светлячки, дождь/туман/гроза, луна. --new --weather --tod --age
Фон (19.10.2026): холмы/горы/озеро/деревня/мельница, клавиша b; таймлапс — l.
Окружение (19.10.2026): дневное небо, солнце с лучами, облака, радуга после дождя, падающие звёзды; плоды (зреют, падают), сугробы и лужи с кругами,
трава, цветы, грибы, слоями опавшие листья; сова ночью, белка днём, олень изредка; в ∞ время суток идёт само (CLOCK_RATE, сутки ≈ 4 мин).
Жизнь (19.10.2026): срезанные куски дают ростки; плод с земли кликом — в корзину; огонь: f — зажигалка; e — декор: дупло с совой/белкой, плющ, качели, домик на дереве (авто — по seed, все, нет).
Снимок:  tree.py --shot out.png [--size 100x50] [--scale 8]      (кадр = то, что увидит панель)
Видео:   tree.py --video out.mp4 [--seconds 24] [--size 100x50]
"""
import argparse, datetime, json, math, os, random, re, select, shutil, struct, subprocess, sys, termios, time, tty, zlib
import numpy as np
from zoneinfo import ZoneInfo

FALLBACK_BG = (0x2d, 0x35, 0x3b)
SPEEDS = [0, .25, .5, 1, 2, 4, 8, 16]   # множитель скорости роста (←→)
MATURE = 1800.0                         # «секунд роста» до полной зрелости: толстый ствол, густая крона
STATE = os.path.expanduser('~/.cache/tree/state.json')
# погода: (дождь, туман, гроза)
WEATHER = {'clear': (0, 0, 0), 'rain': (1, .15, 0), 'fog': (0, .9, 0), 'storm': (1, .1, 1)}
WX_NAMES = {'clear': 'ясно', 'rain': 'дождь', 'fog': 'туман', 'storm': 'гроза'}
TOD_NAMES = {'auto': 'авто', 'day': 'день', 'dusk': 'закат', 'night': 'ночь'}
# свет: (множитель цвета, «ночность»)
L_DAY, L_DUSK, L_DAWN, L_NIGHT = ((1, 1, 1), 0), ((1, .70, .55), .35), ((.95, .80, .78), .35), ((.30, .38, .62), 1)
LIGHT = {'day': L_DAY, 'dusk': L_DUSK, 'night': L_NIGHT}
DAY_KEYS = [(0, L_NIGHT), (5, L_NIGHT), (7, L_DAWN), (9, L_DAY), (17, L_DAY), (19.5, L_DUSK), (22, L_NIGHT), (24, L_NIGHT)]
BIRDS = [((38, 40, 52), (140, 145, 160)), ((120, 86, 62), (214, 96, 56)), ((60, 96, 150), (232, 205, 92))]
BFLY = [(240, 160, 40), (240, 240, 230), (110, 160, 240)]
SEASON_NAMES = ['spring', 'summer', 'autumn', 'winter']
CLOCK_RATE = 0.1                         # в бесконечном режиме: часов суток за секунду (сутки ≈ 4 мин)
# фон за деревом (19.10.2026): холмы, горы, озеро, деревня с дымом, мельница; при каждом новом дереве случайный
BD_KINDS = ['hills', 'mountains', 'lake', 'village', 'windmill']
BD_RU = {'rand': 'случайно', 'none': 'нет', 'hills': 'холмы', 'mountains': 'горы', 'lake': 'озеро', 'village': 'деревня', 'windmill': 'мельница'}
BD_HILL = {'spring': (126, 178, 94), 'summer': (82, 140, 68), 'autumn': (178, 130, 66), 'winter': (228, 236, 246)}
BD_WATER = {'spring': (74, 124, 176), 'summer': (66, 116, 170), 'autumn': (84, 112, 142), 'winter': (206, 224, 238)}
TL_DUR = 60.0                            # таймлапс: секунд на всю жизнь дерева (3 года по 4 сезона)
# плод на дереве: (цвет зрелого, цвет незрелого)
FRUIT = {'oak': ((150, 105, 52), (96, 132, 52)), 'sakura': ((196, 24, 52), (120, 150, 60)), 'birch': ((236, 196, 64), (130, 160, 60)),
         'acacia': ((196, 164, 72), (110, 140, 58)), 'pine': ((126, 84, 52), (80, 110, 56)), 'willow': ((190, 200, 120), (120, 160, 70)),
         'apple': ((206, 36, 40), (112, 150, 62))}
FLOWERS = [(255, 238, 120), (255, 255, 255), (240, 130, 170), (176, 150, 240)]
RAINBOW = np.array([(148, 0, 211), (75, 0, 200), (40, 80, 255), (40, 200, 70), (255, 240, 50), (255, 140, 20), (255, 40, 40)], np.float32)
HB, HL = (112, 88, 68), (172, 142, 108)           # ёж
FX, FW, FK = (214, 104, 40), (240, 236, 226), (46, 32, 28)  # лиса
NEST, NEST2 = (122, 88, 54), (156, 114, 68)
GCRIT = dict(hedgehog=dict(v=4.0, t=(60, 150)), fox=dict(v=11.0, t=(150, 400)), snail=dict(v=.8, t=(20, 40)))
DEER_BODY, DEER_LIGHT, DEER_HORN = (150, 105, 66), (196, 156, 108), (214, 204, 172)

# Лиственные деревья растут симуляцией (Tree.simulate): у каждого дерева свои случайные параметры.
# life0 — шагов жизни ствола; pb/pf — вероятность бокового побега / развилки за шаг; clife — доля жизни у ответвления;
# spread — угол ответвления; jit — дрожание направления; trop — тяга вверх; droop — провисание; amax — предел угла;
# avoid — уход от соседних веток; dens/lam/hmax — листья по числу шагов до кончика ветки; reach — разброс листа вокруг
# ветки (доля высоты панели); aspect — вытянутость разброса; crown — допустимое отношение ширины кроны к высоте.
PRESETS = {
    'oak':    dict(L=1.6, life0=16, lean=.05, jit=.10, trop=.10, amax=1.9, spread=.80, pb=.50, pf=.10, clife=.75, minage=2, maxord=6,
                   droop=.05, avoid=.9, cthr=4, pend=.65, dens=14.0, lam=2.6, hmax=6, reach=.026, tipleaf=7, delay=3,
                   aspect=(1.0, .85), crown=(.8, 1.8)),
    'sakura': dict(L=1.6, life0=15, lean=.22, jit=.16, trop=.06, amax=2.1, spread=.90, pb=.48, pf=.14, clife=.75, minage=2, maxord=6,
                   droop=.08, avoid=.9, cthr=4, pend=.65, dens=14.0, lam=2.6, hmax=6, reach=.024, tipleaf=7, delay=3,
                   aspect=(1.2, .75), crown=(.9, 2.0)),
    'birch':  dict(L=1.6, life0=19, tmin=6, lean=.06, jit=.08, trop=.30, amax=1.4, spread=.50, pb=.50, pf=.05, clife=.68, minage=3, maxord=6,
                   droop=.04, avoid=.9, cthr=4, pend=.6, dens=11.0, lam=2.6, hmax=6, reach=.020, tipleaf=6, delay=3,
                   aspect=(.85, 1.1), crown=(.3, .95), bark=(214, 208, 196)),
    'acacia': dict(L=1.6, life0=17, tmin=9, lean=.15, jit=.12, trop=-.16, amax=1.45, spread=1.10, pb=.45, pf=.16, clife=.75, minage=2, maxord=6,
                   droop=.0, avoid=.9, cthr=4, pend=.65, dens=15.0, lam=2.4, hmax=5, reach=.020, tipleaf=7, delay=3,
                   aspect=(2.3, .45), crown=(1.4, 3.4), minh=24),
    'willow': dict(L=1.6, life0=15, tmin=6, lean=.05, jit=.12, trop=-.02, amax=2.5, spread=.75, pb=.45, pf=.12, clife=.8, minage=2, maxord=6,
                   droop=.34, avoid=.9, cthr=4, pend=.8, dens=16.0, lam=2.6, hmax=9, reach=.018, tipleaf=9, delay=3,
                   aspect=(.8, 1.5), crown=(.7, 1.7)),
    'pine':   dict(conifer=True, leafR=.026, leaves=30, aspect=(1.7, .55)),
}

PRESETS['apple'] = dict(PRESETS['oak'], reach=.03, aspect=(1.15, .8), crown=(1.0, 2.0), bark=(104, 78, 58))   # яблоня: широкая крона, белый цвет весной, красные яблоки

# палитры листвы: (цвет, вес)
SEASONS = {
    'spring': dict(pal=[((120, 200, 90), 3), ((160, 220, 110), 3), ((90, 170, 80), 2), ((255, 205, 218), 1.3)],
                   bark=(98, 72, 54), ground=((96, 168, 74), (46, 92, 48)), fall='petal', fcol=(255, 205, 220), glow=(40, 30, 40)),
    'summer': dict(pal=[((46, 125, 50), 3), ((76, 160, 60), 3), ((120, 190, 70), 2), ((30, 92, 46), 2)],
                   bark=(92, 66, 46), ground=((84, 150, 62), (40, 86, 44)), fall=None, fcol=None, glow=(30, 38, 20)),
    'autumn': dict(pal=[((214, 90, 30), 3), ((235, 150, 40), 3), ((190, 50, 30), 2), ((240, 200, 60), 2), ((130, 100, 30), 1)],
                   bark=(88, 62, 44), ground=((150, 118, 52), (78, 58, 40)), fall='leaf', fcol=None, glow=(60, 30, 8)),
    'winter': dict(pal=None, bark=(128, 116, 112), ground=((236, 241, 249), (160, 176, 200)), fall='snow',
                   fcol=(245, 248, 255), glow=(20, 28, 44)),
}
APPLE_SPRING = [((255, 244, 244), 3), ((250, 214, 222), 2.5), ((255, 255, 255), 2), ((120, 175, 95), 1.2)]
SAKURA_SPRING = [((255, 183, 197), 3), ((248, 150, 180), 2), ((255, 226, 233), 2.5), ((230, 120, 160), 1), ((120, 175, 95), .5)]


def ridge(rng, n, octs, smooth=True, ridged=False):
    """Одномерный шум 0..1 длиной n: холмы (гладко) или горы (острые пики)."""
    tot, amp, out = 0.0, 1.0, np.zeros(n)
    for o in range(octs):
        k = 2 + 2 ** (o + 1)
        xs = np.linspace(0, k, n)
        i = np.minimum(xs.astype(int), k - 1)
        f = xs - i
        if smooth:
            f = f * f * (3 - 2 * f)
        pts = rng.random(k + 1)
        v = pts[i] + (pts[i + 1] - pts[i]) * f
        out += (1 - np.abs(2 * v - 1) if ridged else v) * amp
        tot += amp
        amp *= .5
    out /= tot
    return (out - out.min()) / max(1e-6, out.max() - out.min())


def smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def season_now():
    m = datetime.date.today().month
    return 'winter' if m in (12, 1, 2) else 'spring' if m in (3, 4, 5) else 'summer' if m in (6, 7, 8) else 'autumn'


class Tree:
    """Геометрия: список отрезков и «кончиков» (под листву). Всё в пикселях, y вниз."""

    def __init__(s, pw, ph, preset, seed):
        s.pw, s.ph, s.preset, s.seed = pw, ph, preset, seed
        P = PRESETS[preset]
        s.P = P
        s.rnd = random.Random(seed)
        s.gy = ph * 0.86
        s.mound = ph * 0.035
        s.cx = pw * 0.5
        s.rooty = s.gnd(s.cx) + 1
        s.segs, s.tips, s.par = [], [], []
        r0 = max(1.3, ph * 0.026) if s.P.get('conifer') else max(1.0, ph * 0.015)
        if s.P.get('conifer'):
            s.conifer(r0)
        else:
            s.generate(r0)
        for sg in (-1, 1):  # раструб корней — виден сразу
            s.segs.append((s.cx, s.rooty - r0 * .4, s.cx + sg * r0 * 1.7, s.rooty + 0.4, r0 * .8, .45, -2, -1))
            s.par.append(-2)  # корни не режутся
        s.fit(r0)
        S = np.array(s.segs, np.float32)
        s.S = S
        s.parl = s.par
        s.par = np.array(s.par)
        s.maxb = float(S[:, 7].max())
        s.thk = ((S[:, 4] / S[:, 4].max()) ** .5).astype(np.float32)  # насколько ветка толстеет с возрастом
        s.top = float(min(S[:, 1].min(), S[:, 3].min()))
        s.th = max(1.0, s.gy - s.top)
        s.build_leaves()

    def fit(s, r0):
        """Масштабирует дерево так, чтобы крона влезла в панель (рост от корня)."""
        P = s.P
        xs = [t[0] for t in s.tips] + [g[2] for g in s.segs]
        ys = [t[1] for t in s.tips] + [g[3] for g in s.segs]
        pad = (P['leafR'] * s.ph * 2.2) if P.get('conifer') else P['reach'] * s.ph * 3
        hgt = s.rooty - min(ys) + pad * P['aspect'][1]
        wid = (max(xs) - min(xs)) + 2 * pad * P['aspect'][0]
        half = max(s.cx - min(xs), max(xs) - s.cx) + pad * P['aspect'][0]
        f = min(.80 * s.ph / hgt, .46 * s.pw / half)
        if P.get('conifer'):
            f = min(f, 1.15) if f >= 1 else f
        cx, ry = s.cx, s.rooty

        def X(x): return cx + (x - cx) * f

        def Y(y): return ry + (y - ry) * f
        s.segs = [(X(a), Y(b), X(c), Y(d), max(e * f, .3), max(g * f, .25), h * f, i * f) if h >= 0 else
                  (a, b, c, d, e, g, h, i) for a, b, c, d, e, g, h, i in s.segs]
        s.tips = [(X(x), Y(y), b * f, w, p) for x, y, b, w, p in s.tips]

    def gnd(s, x):
        return s.gy - s.mound * np.exp(-(((x - s.pw * .5) / (s.pw * .32)) ** 2))

    # ---------- симуляция роста ----------
    def generate(s, r0):
        """Растит дерево: у каждого семени своя форма. Считается в условных единицах (не зависит от размера панели),
        потом переносится на панель — одно семя даёт одну и ту же топологию при любом размере."""
        best = None
        for attempt in range(30):
            res = s.simulate(random.Random(s.seed * 7919 + attempt))
            pen = s.quality(res)
            if best is None or pen < best[0]:
                best = (pen, res)
            if pen == 0:
                break
        X0, Y0, X1, Y1, B0, B1, PAR = best[1]
        n = len(PAR)
        kids = [[] for _ in range(n)]
        for j, p in enumerate(PAR):
            if p >= 0:
                kids[p].append(j)
        # толщина по pipe-модели: сечение родителя = сумма сечений детей (+ немного древесины на звено)
        D, eps = 2.3, .22
        A = [0.0] * n
        for j in range(n - 1, -1, -1):
            A[j] = sum(A[c] for c in kids[j]) + eps ** D if kids[j] else .3 ** D
        rad = np.array(A) ** (1 / D)
        rad *= r0 / rad[0]
        k = s.ph / 100.0
        P = s.P
        sx = max(.6, min(1.0, (s.pw / s.ph) / .95))  # узкая панель — узкая крона
        s.hop = [0] * n
        for j in range(n - 1, -1, -1):
            s.hop[j] = 1 + min(s.hop[c] for c in kids[j]) if kids[j] else 0
        for j in range(n):
            xa, xb = s.cx + X0[j] * k * sx, s.cx + X1[j] * k * sx
            ya, yb = s.rooty + Y0[j] * k, s.rooty + Y1[j] * k
            s.segs.append((xa, ya, xb, yb, rad[j], rad[j] * .93, B0[j], B1[j]))
            s.par.append(PAR[j])
            if not kids[j]:
                s.tips.append((xb, yb, B1[j], 1.0, j))

    def simulate(s, rnd):
        """Живой рост: у каждой верхушки счётчик жизни; она шагает, колеблется, тянется вверх, огибает чужие ветки,
        по вероятности даёт боковой побег или развилку и умирает, когда жизнь кончилась или стало тесно."""
        P = s.P
        v = lambda x, j: x * rnd.uniform(1 - j, 1 + j)  # у каждого дерева свои параметры
        life0, spread, jit, trop = max(7, round(v(P['life0'], .15))), v(P['spread'], .15), v(P['jit'], .25), v(P['trop'], .3) if P['trop'] > 0 else P['trop']
        pb, pf, clife, avoid, pend = v(P['pb'], .2), v(P['pf'], .4), min(.85, v(P['clife'], .08)), P['avoid'], min(.95, v(P['pend'], .15))
        amax, droop, minage, maxord = P['amax'], P['droop'], P['minage'], P['maxord']
        tmin = P.get('tmin', minage + 1)  # сколько шагов ствол голый
        lam = rnd.uniform(.48, .58)  # >.5 — сила идёт к главной оси (апикальный контроль)
        lean = P['lean'] * rnd.choice((-1, 1)) * rnd.uniform(.3, 1.5) + rnd.gauss(0, .05)
        L = P.get('L', 2.2)
        CELL = 3.0
        Hh = life0 * L * 1.5
        cy, ry = .62 * Hh, .5 * Hh
        rx = ry * max(.35, min(2.4, sum(P['crown']) / 2)) * 1.15
        crowd = {}

        def cnt(x, y, lin):  # сколько чужих (не из своей родословной) узлов рядом
            cx, cy = int(x // CELL), int(y // CELL)
            return sum(1 for i in (-1, 0, 1) for j in (-1, 0, 1) for b in crowd.get((cx + i, cy + j), ()) if b not in lin)

        X0, Y0, X1, Y1, B0, B1, PAR = [], [], [], [], [], [], []
        # верхушка: [x, y, угол, жизнь, порядок, родительский отрезок, старт, скорость, возраст, сторона, жизнь0, номер ветки, родословная]
        nb = [1]

        def newb(lin):
            nb[0] += 1
            return nb[0], lin | {nb[0]}
        active = [[0.0, 0.0, lean, life0, 0, -1, 0, 1.0, 0, rnd.choice((-1, 1)), life0, 1, frozenset((1,))]]
        r = 0
        while active and len(X0) < 2300 and r < 500:
            nxt = []
            for ap in active:
                x, y, a, life, order, par, start, speed, age, side, l0, bid, lin = ap
                if r < start:
                    nxt.append(ap)
                    continue
                a += rnd.gauss(0, jit * (1 + .2 * order))
                a -= trop * (1 if order <= 1 else .6) * math.sin(a)  # момент тяги ∝ |H×T| (ABOP, гл. 2)
                if order >= 2 and droop:
                    a += math.copysign(droop, a if abs(a) > .05 else side) * (age / l0)
                pl = cnt(x + math.sin(a - .7) * L * 2.2, y - math.cos(a - .7) * L * 2.2, lin)
                pr = cnt(x + math.sin(a + .7) * L * 2.2, y - math.cos(a + .7) * L * 2.2, lin)
                a += max(-.3, min(.3, (pl - pr) * avoid * .12))
                am = amax if order else min(amax, .6)
                a = max(-am, min(am, a))
                # огибающая кроны (Runions 2007): вне неё жизнь тратится быстрее, а ветка заворачивает внутрь
                ex = (x / rx) ** 2 + ((y + cy) / ry) ** 2
                if ex > 1 and order > 0:
                    to = math.atan2(-x, cy + y) if abs(cy + y) > 1e-6 else 0.0
                    a += max(-.25, min(.25, (to - a) * .12 * min(2.0, ex - 1 + .3)))
                    life -= .35 * min(2.0, ex - 1)
                step = L * speed * rnd.uniform(.85, 1.15)
                nx, ny = x + math.sin(a) * step, y - math.cos(a) * step
                if ny > -1.5 and order > 0:
                    continue  # ушла в землю
                j = len(X0)
                X0.append(x); Y0.append(y); X1.append(nx); Y1.append(ny)
                B0.append(r); B1.append(r + 1); PAR.append(par)
                ck = (int(nx // CELL), int(ny // CELL))
                c0 = cnt(nx, ny, lin)
                cl = crowd.setdefault(ck, [])
                if len(cl) < 10:
                    cl.append(bid)
                life -= 1 + (1 if order >= 1 and c0 > P['cthr'] else 0)
                age += 1
                done = life <= 0
                if not done and age >= (tmin if order == 0 else minage) and life > 2 and order < maxord:
                    if rnd.random() < pb * (1 - order * .05) / (1 + .18 * c0):  # боковой побег (апикальное доминирование: ствол идёт дальше)
                        side = -side
                        la = a + side * spread * rnd.uniform(.75, 1.25) + rnd.gauss(0, .1)
                        # распределение «жизненной силы» по свету (Palubicki 2009): Q — доля свободного места впереди
                        qm = 1 / (1 + cnt(nx + math.sin(a) * L * 3, ny - math.cos(a) * L * 3, lin))
                        ql = 1 / (1 + cnt(nx + math.sin(la) * L * 3, ny - math.cos(la) * L * 3, lin))
                        share = 2 * (1 - lam) * ql / (lam * qm + (1 - lam) * ql)
                        ll = int(round(l0 * clife * rnd.uniform(.8, 1.15) * max(.35, min(1.5, share))))
                        if ll >= 2 and ql > .12:  # в тени почка не раскрывается
                            b2, l2 = newb(lin)
                            nxt.append([nx, ny, la, ll, order + 1, j,
                                        r + 1 + int(rnd.uniform(0, P['delay'] + 1)), speed * rnd.uniform(.85, 1.0), 0, rnd.choice((-1, 1)), ll, b2, l2])
                    elif life >= 4 and order <= maxord - 2 and rnd.random() < pf / (1 + .18 * c0):  # развилка: верхушка делится надвое
                        for sd in (-1, 1):
                            ll = int(life * .82)
                            b2, l2 = newb(lin)
                            nxt.append([nx, ny, a + sd * spread * rnd.uniform(.4, .8), ll, order + 1, j, r + 1, speed * rnd.uniform(.9, 1.0),
                                        0, sd, ll, b2, l2])
                        done = True
                if done and order < maxord and l0 >= 3 and rnd.random() < pend:  # конец ветки: раздваивается на веточки
                    for sd in (-1, 1):
                        ll = max(2, int(l0 * rnd.uniform(.42, .62)))
                        b2, l2 = newb(lin)
                        nxt.append([nx, ny, a + sd * spread * rnd.uniform(.5, 1.0), ll, order + 1, j, r + 1, speed * rnd.uniform(.9, 1.0),
                                    0, sd, ll, b2, l2])
                if not done:
                    ap[0], ap[1], ap[2], ap[3], ap[5], ap[8], ap[9] = nx, ny, a, life, j, age, side
                    nxt.append(ap)
            active = nxt
            r += 1
        return X0, Y0, X1, Y1, B0, B1, PAR

    def quality(s, res):
        """0 — дерево годится; иначе штраф. Отсеивает палки, комки и перекошенные кроны."""
        X0, Y0, X1, Y1, B0, B1, PAR = res
        n = len(PAR)
        if n < 200:
            return 100
        has = set(PAR)
        tips = [j for j in range(n) if j not in has]
        tx = np.array([X1[j] for j in tips])
        ty = np.array([Y1[j] for j in tips])
        h = -min(Y1)
        w = max(X1) - min(X1)
        lo, hi = s.P['crown']
        pen = 0.0
        if len(tips) < 30:
            pen += 5
        pen += max(0, lo - w / max(h, 1)) * 10 + max(0, w / max(h, 1) - hi) * 10
        pen += max(0, abs(float(tx.mean())) / max(w / 2, 1) - .30) * 10
        pen += max(0, s.P.get("minh", 32) - h) * 1.0
        if h > 400 or n >= 2300:
            pen += 5
        return pen

    def conifer(s, r0):
        rnd, ph = s.rnd, s.ph
        H, n = ph * .74, 12
        x, y, b, step = s.cx, s.rooty, 0.0, ph * .74 / 12
        nodes = []
        for i in range(n):
            nx, ny = x + rnd.gauss(0, .5), y - step
            s.segs.append((x, y, nx, ny, r0 * (1 - i / n * .85), r0 * (1 - (i + 1) / n * .85), b, b + step))
            s.par.append(len(s.segs) - 2 if i else -1)
            b += step
            x, y = nx, ny
            if i >= 2:
                nodes.append((x, y, b, i / n, len(s.segs) - 1))
        s.tips.append((x, y, b, 1.4, len(s.segs) - 1))
        for x, y, b0, h, nseg in nodes:
            for _ in range(2):
                for sg in (-1, 1):
                    L = ((1 - h) ** .85 * .27 + .03) * ph * rnd.uniform(.8, 1.1)
                    a = sg * rnd.uniform(1.25, 1.5)
                    bx, by, bb, m = x, y, b0, 4
                    bpar = nseg
                    for k in range(m):
                        a += sg * .13
                        nx, ny = bx + math.sin(a) * L / m, by - math.cos(a) * L / m
                        s.segs.append((bx, by, nx, ny, .8 - k * .12, .8 - (k + 1) * .12, bb, bb + L / m))
                        s.par.append(bpar)
                        bpar = len(s.segs) - 1
                        bb += L / m
                        bx, by = nx, ny
                        s.tips.append((bx, by, bb, 1.0 if k else .6, bpar))
                y -= step * .45  # второй ярус чуть выше

    def build_leaves(s):
        if s.P.get('conifer'):
            return s.build_leaves_conifer()
        P, S = s.P, s.S
        rng = np.random.default_rng(s.seed + 1)
        n = len(S)
        hop = np.array(s.hop + [99] * (n - len(s.hop)), float)  # шагов до кончика ветки (корни — далеко)
        lam = np.where(hop <= P['hmax'], P['dens'] * np.exp(-hop / P['lam']), 0.0)
        lam += np.where(hop == 0, P['tipleaf'], 0.0)
        cnt = rng.poisson(lam)
        idx = np.repeat(np.arange(n), cnt)
        N = len(idx)
        u = rng.random(N)
        ring = rng.random(N) < .3           # внешнее кольцо — гуще крона, позже
        sig = P['reach'] * s.ph
        nz = np.clip(rng.normal(0, 1, (2, N)), -2, 2) * np.where(ring, 2.0, 1.0)
        ox, oy = nz[0] * sig * P['aspect'][0], nz[1] * sig * P['aspect'][1]
        px = S[idx, 0] + (S[idx, 2] - S[idx, 0]) * u
        py = S[idx, 1] + (S[idx, 3] - S[idx, 1]) * u
        s.lloc = (-nz[1] * .5 - nz[0] * .25).astype(np.float32) / np.where(ring, 2.0, 1.0)
        s.lseg = idx
        s.lx = (px + ox).astype(np.float32)
        s.ly = np.minimum((py + oy).astype(np.float32), s.gnd(s.lx) - 1)
        # лист появляется, когда кора дошла до его точки; потом — чем дальше от ветки, тем позже
        bu = S[idx, 6] + (S[idx, 7] - S[idx, 6]) * u
        far = np.hypot(nz[0], nz[1]) / np.where(ring, 2.0, 1.0) + ring * 1.5
        s.lb = np.minimum(bu + s.maxb * (.025 + .03 * far + rng.uniform(0, .02, N)), 1.22 * s.maxb)
        s.lu = rng.random(N)
        s.lph = rng.uniform(0, 6.283, N).astype(np.float32)
        s.back = rng.random(N) < .3
        ymin, ymax = s.ly.min(), s.ly.max()
        xmin, xmax = s.lx.min(), s.lx.max()
        s.ll = np.clip(1 - (s.ly - ymin) / max(1, ymax - ymin), 0, 1) * .8 + \
            np.clip(1 - (s.lx - xmin) / max(1, xmax - xmin), 0, 1) * .2
        s.lj = rng.uniform(.9, 1.1, N).astype(np.float32)
        s.lfull = rng.random(N).astype(np.float32)

    def build_leaves_conifer(s):
        P = s.P
        rng = np.random.default_rng(s.seed + 1)
        T = np.array(s.tips, np.float32)
        cnt = np.maximum(1, np.round(P['leaves'] * T[:, 3]).astype(int))
        idx = np.repeat(np.arange(len(T)), cnt)
        N = len(idx)
        sig = P['leafR'] * s.ph
        nz = np.clip(rng.normal(0, 1, (2, N)), -2, 2)
        ox = nz[0] * sig * P['aspect'][0]
        oy = nz[1] * sig * P['aspect'][1]
        s.lloc = (-nz[1] * .5 - nz[0] * .25).astype(np.float32)  # свет внутри пучка: сверху-слева
        s.lseg = T[idx, 4].astype(int)
        s.lx = (T[idx, 0] + ox).astype(np.float32)
        s.ly = (T[idx, 1] + oy).astype(np.float32)
        s.ly = np.minimum(s.ly, s.gnd(s.lx) - 1)
        s.lb = T[idx, 2] + rng.uniform(0, .06 * s.maxb, N)
        s.lu = rng.random(N)
        s.lph = rng.uniform(0, 6.283, N).astype(np.float32)
        s.back = rng.random(N) < .3
        ymin, ymax = s.ly.min(), s.ly.max()
        xmin, xmax = s.lx.min(), s.lx.max()
        s.ll = np.clip(1 - (s.ly - ymin) / max(1, ymax - ymin), 0, 1) * .8 + \
            np.clip(1 - (s.lx - xmin) / max(1, xmax - xmin), 0, 1) * .2
        s.lj = rng.uniform(.9, 1.1, N).astype(np.float32)
        s.lfull = rng.random(N).astype(np.float32)  # молодая крона показывает не все листья

    def descend(s, hit):
        """Отрезки из hit и всё, что на них растёт (родитель всегда с меньшим номером)."""
        sev, par = hit.tolist(), s.parl
        for j in range(len(par)):
            if par[j] >= 0 and sev[par[j]]:
                sev[j] = True
        return np.array(sev)

    def leaf_colors(s, season):
        pal = SEASONS[season]['pal']
        if pal is None:
            return None
        if s.preset == 'sakura' and season == 'spring':
            pal = SAKURA_SPRING
        elif s.preset == 'apple' and season == 'spring':
            pal = APPLE_SPRING
        cols = np.array([c for c, _ in pal], np.float32)
        w = np.array([w for _, w in pal], np.float32)
        edges = np.cumsum(w) / w.sum()
        k = np.searchsorted(edges, s.lu).clip(0, len(cols) - 1)
        light = (.55 + .42 * s.ll + .16 * s.lloc) * s.lj * np.where(s.back, .62, 1.0)
        return np.clip(cols[k] * light[:, None], 0, 255).astype(np.float32)


class Piece:
    """Срезанный кусок: жёсткое тело (отрезки + листья), падает, крутится, лежит, его можно толкать."""

    def __init__(p, sc, segs, g, lk, lx, ly, pivot):
        x0, y0, x1, y1, r0, r1, f = g
        xs = np.concatenate([x0[segs], x1[segs], lx[lk]])
        ys = np.concatenate([y0[segs], y1[segs], ly[lk]])
        p.cx, p.cy = float(xs.mean()), float(ys.mean())
        p.seg = np.stack([x0[segs] - p.cx, y0[segs] - p.cy, x1[segs] - p.cx, y1[segs] - p.cy])
        p.r0, p.r1 = r0[segs], r1[segs]
        p.lrel = np.stack([lx[lk] - p.cx, ly[lk] - p.cy])
        p.lc = sc.cols[lk].copy() if sc.cols is not None and len(lk) else np.zeros((0, 3), np.float32)
        p.rad = float(np.hypot(xs - p.cx, ys - p.cy).max()) if len(xs) else 1.0
        p.th, p.vx, p.vy = 0.0, random.uniform(-4, 4), 0.0
        p.w = max(-3.0, min(3.0, (p.cx - pivot[0]) * .15)) + random.uniform(-.5, .5)
        p.rest, p.contact, p.age, p.alpha = False, 0.0, 0.0, 1.0
        p.fell, p.log, p.landed, p.sq, p.yref = None, False, False, 1.0, 0.0
        px = np.concatenate([p.seg[0], p.seg[2]])
        py = np.concatenate([p.seg[1], p.seg[3]])
        ev = np.linalg.eigh(np.cov(np.stack([px, py])) + np.eye(2) * 1e-6)[1][:, 1]
        p.axis = math.atan2(ev[1], ev[0])  # главная ось куска; лёжа она должна стать горизонтальной

    def world(p):
        c, s = math.cos(p.th), math.sin(p.th)
        sx, sy = p.seg, p.seg
        x0, y0 = p.cx + c * sx[0] - s * sx[1], p.cy + s * sx[0] + c * sx[1]
        x1, y1 = p.cx + c * sy[2] - s * sy[3], p.cy + s * sy[2] + c * sy[3]
        lx, ly = p.cx + c * p.lrel[0] - s * p.lrel[1], p.cy + s * p.lrel[0] + c * p.lrel[1]
        if p.sq != 1.0:   # упавшая крона мнётся: по вертикали сплющивается к линии ствола
            r = p.yref
            y0, y1, ly = r + (y0 - r) * p.sq, r + (y1 - r) * p.sq, r + (ly - r) * p.sq
        return x0, y0, x1, y1, lx, ly

    def start_fall(p, pivot, d):
        """Валка ствола: кусок поворачивается вокруг основания (pivot) в сторону d (±1), пока не ляжет."""
        p.fell = [pivot[0], pivot[1], p.cx - pivot[0], p.cy - pivot[1], 0.02, 0.0, 1 if d >= 0 else -1]
        p.yref = pivot[1]
        p.log, p.landed = True, False

    def fall_step(p, dt, sc):
        px, py, rx, ry, phi, om, d = p.fell
        om += (2.6 * math.sin(phi + .2) + .25) * dt        # момент силы тяжести растёт, пока ствол кренится
        om *= math.exp(-.25 * dt)
        phi += om * dt
        th = d * phi
        c, s_ = math.cos(th), math.sin(th)
        p.th, p.cx, p.cy = th, px + c * rx - s_ * ry, py + s_ * rx + c * ry
        p.sq = 1 - .68 * smoothstep((phi - .6) / .8)
        x0, y0, x1, y1, lx, ly = p.world()
        X, Y = np.concatenate([x0, x1]), np.concatenate([y0, y1])   # о землю бьют ветки, листва мягкая
        pen = float((Y - (sc.tree.gnd(np.clip(X, 0, sc.pw - 1)) - .5)).max())
        if phi > 1.42:   # ствол лёг; ветки, ушедшие в траву, приподнимают его (лежит на кроне), что ниже земли — не рисуем
            phi = math.pi / 2                                # ложится ровно горизонтально, а не под углом ~81°
            th = d * phi
            c, s_ = math.cos(th), math.sin(th)
            p.th, p.cx, p.cy = th, px + c * rx - s_ * ry, py + s_ * rx + c * ry
            p.sq = 1 - .68
            x0, y0, x1, y1, lx, ly = p.world()
            X, Y = np.concatenate([x0, x1]), np.concatenate([y0, y1])
            pen = float((Y - (sc.tree.gnd(np.clip(X, 0, sc.pw - 1)) - .5)).max())
            delta = pen if pen < 0 else max(0.0, pen - 1.2)   # завис над землёй — опускаем, ушёл в траву — приподнимаем (не выше 6% высоты)
            p.cy -= min(delta, sc.ph * .06)
            p.rest, p.landed, p.fell, p.age = True, True, None, 0.0
        else:
            p.fell[4], p.fell[5] = phi, om

    def step(p, dt, sc):
        if getattr(p, 'fell', None):
            return p.fall_step(dt, sc)
        if p.rest:
            p.age += dt
            if getattr(p, 'log', False):
                p.alpha = 1.0   # бревно не тает: лежит, обрастает мхом
                return
            if not getattr(p, 'seeded', False) and p.age > 1.5:   # упавший кусок даёт росток рядом
                p.seeded = True
                if random.random() < .7 and not getattr(p, 'burn', 0):
                    sc.try_plant(float(np.clip(p.cx + random.uniform(-3, 3), 4, sc.pw - 4)))
            p.alpha = 1.0 if p.age < 8 else max(0.0, 1 - (p.age - 8) / 3)  # полежал и растаял
            return
        p.vy += 170 * dt
        p.vx *= math.exp(-.6 * dt)
        p.vy *= math.exp(-.25 * dt)
        p.w *= math.exp(-.8 * dt)
        p.cx += p.vx * dt
        p.cy += p.vy * dt
        p.th += p.w * dt
        x0, y0, x1, y1, lx, ly = p.world()
        X, Y = np.concatenate([x0, x1, lx]), np.concatenate([y0, y1, ly])
        pen = float((Y - (sc.tree.gnd(X) - .5)).max()) if len(X) else 0.0
        if pen > 0:
            p.cy -= pen
            p.vy = -p.vy * .18 if p.vy > 20 else 0.0
            p.vx *= .6
            p.w = 0.0
            flat = -p.axis + round((p.th + p.axis) / math.pi) * math.pi  # ближайший угол, где ось горизонтальна
            p.th += (flat - p.th) * min(1.0, 5 * dt)
            p.contact += dt
            if p.contact > .6 and abs(p.vx) < 4 and abs(flat - p.th) < .05:
                p.rest, p.vx, p.vy, p.w = True, 0.0, 0.0, 0.0
        else:
            p.contact = 0.0
        p.cx = min(max(p.cx, 0), sc.pw)


class Bird:
    """Птица: прилетает, садится на ветку, сидит, перескакивает, улетает (или спугнули)."""

    def __init__(b, x, y, seg, u):
        b.x, b.y, b.seg, b.u = x, y, seg, u
        b.state, b.face = 'in', 1
        b.wait, b.look, b.vx, b.vy = random.uniform(6, 16), random.uniform(2, 5), 0.0, 0.0
        b.back, b.belly = random.choice(BIRDS)

    def leave(b, pw):
        if b.state != 'out':
            b.state = 'out'
            b.face = 1 if b.x > pw / 2 else -1
            b.vx, b.vy = b.face * random.uniform(22, 32), -random.uniform(10, 18)


# ---------- жизнь дерева (19.10.2026, пятый заход): топор и пень, бревно, семена, молния, декор ----------
TOOLS = ['cut', 'prune', 'axe', 'plant']
TOOL_RU = {'cut': 'срез', 'prune': 'форма', 'axe': 'топор', 'plant': 'семя'}
DECO_RU = {'auto': 'авто', 'all': 'все', 'none': 'нет'}
DIGITS = {'0': '111101101101111', '1': '010110010010111', '2': '111001111100111', '3': '111001111001111', '4': '101101111001001',
          '5': '111100111001111', '6': '111100111101111', '7': '111001001001001', '8': '111101111101111', '9': '111101111001111'}
WOOD, WOOD_D, WOOD_L = (206, 168, 120), (170, 128, 86), (222, 190, 146)
MOSS = [(74, 124, 54), (96, 146, 62), (58, 104, 50)]
CHAR = (28, 24, 22)
MAX_SAPS = 6


class Life:
    """Топор/пень/бревно, обрезка «форма» (память), саженцы, молния в дерево, дупло/плющ/качели/домик, счётчик урожая."""
    fell_delay = 220.0                      # через сколько «секунд роста» пень даёт новые побеги (бревно успевает зарасти мхом)

    # ---------- состояние ----------
    def reset_life(s):
        n = len(s.tree.par)
        s.perm = np.zeros(n, bool)          # срезано «формой»: не отрастает
        s.scar = np.full(n, -1e9)           # когда обожжён молнией (gt)
        s.chips, s.fire, s.saps, s.hits = [], [], [], {}
        s.stump, s.dead = None, set()
        s.reset_fire()

    def mem_snapshot(s):
        return {(s.preset, s.seed): np.where(s.perm)[0].tolist()} if s.perm.any() else {}

    def apply_memory(s):
        idx = [i for i in s.mem.get((s.preset, s.seed), []) if i < len(s.perm)]
        if not idx:
            return
        tr = s.tree
        s.perm[idx] = True
        s.sevt[idx], s.sevb[idx] = 1e9, tr.S[idx, 6]
        s.update_rf()
        s.lcut[s.perm[tr.lseg]] = True
        s.lcutt[s.perm[tr.lseg]] = s.gt
        rest = np.where(~s.lcut)[0]
        if len(rest):  # листья без коры рядом не висят в воздухе
            dist = s.support_dist(rest, s.perm)
            lost = dist > tr.sup0[rest] + .035 * s.ph
            lost |= ~s.anchored(rest, dist < 2.5)
            s.lcut[rest[lost]] = True
            s.lcutt[rest[lost]] = s.gt
        s.cutv += 1

    def trim_pieces(s):
        logs = [p for p in s.pieces if p.log]
        rest = [p for p in s.pieces if not p.log][-300:]
        s.pieces = logs[-2:] + rest

    # ---------- щепки ----------
    def burst(s, x, y, n, cols, v=18.0, up=14.0):
        for _ in range(n):
            s.chips.append([x + random.uniform(-1, 1), y + random.uniform(-1, 1), random.uniform(-v, v), -random.uniform(2, up),
                            random.choice(cols), s.t])
        del s.chips[:-160]

    def update_chips(s, dt):
        keep = []
        for q in s.chips:
            q[3] += 110 * dt
            q[0] += q[2] * dt
            q[1] += q[3] * dt
            if q[1] < float(s.tree.gnd(min(max(q[0], 0), s.pw - 1))) - .5 and s.t - q[5] < 4:
                keep.append(q)
        s.chips = keep

    def draw_chips(s, buf):
        for q in s.chips:
            s.put(buf, q[0], q[1], q[4])

    # ---------- топор ----------
    def seg_dist(s, g, x, y):
        x0, y0, x1, y1, r0, r1, f = g
        dx, dy = x1 - x0, y1 - y0
        t = np.clip(((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy + 1e-9), 0, 1)
        return np.hypot(x - (x0 + t * dx), y - (y0 + t * dy)) - (r0 + (r1 - r0) * t), t

    def axe_hit(s, x, y):
        """Удар топором. Саженец — сразу долой; ветка — по ударам по толщине; ствол — несколько ударов, дерево падает."""
        z = s.zs()
        for q in s.saps:
            if abs(x - q['x']) < 3.5 * z and q['top'] - 1 < y < q['y'] + 2:
                s.burst(q['x'], q['y'] - 3, 8, [WOOD, WOOD_D, (90, 140, 60)])
                s.saps.remove(q)
                return True
        g = s.geom(s.progress())
        x0, y0, x1, y1, r0, r1, f = g
        d, t = s.seg_dist(g, x, y)
        d = np.where((f > .5) & (s.tree.par != -2), d, 1e9)
        j = int(np.argmin(d))
        if d[j] > 1.4:
            return False
        r = float(r0[j] + (r1[j] - r0[j]) * t[j])
        h = s.hits.get(j)
        if h is None or s.t - h[1] > 7:
            h = [0, s.t]
        h[0] += 1
        h[1] = s.t
        s.hits[j] = h
        need = max(1, round(r * 2.2))
        s.burst(x, y, 7, [WOOD, WOOD_D, WOOD_L], 16, 10)
        s.slash.append(([(x - 2.5, y - 2.5), (x + 2.5, y + 2.5)], s.t))
        s.gust(x, y, random.choice((-1, 1)) * (1.5 + h[0] * .3))
        s.scare(x, y, s.ph * .2)
        if h[0] < need:
            return True
        s.hits.pop(j, None)
        low = bool(s.trunk[j]) and s.chain.index(j) <= .45 * len(s.chain)
        xm, d = (x0[j] + x1[j]) / 2, 1 if x < (x0[j] + x1[j]) / 2 else -1
        room = {1: s.pw - xm, -1: xm}
        if room[d] < .6 * s.gy_h() and room[-d] > room[d]:   # не хватает места — падает туда, где больше
            d = -d
        s.cut_at(j, 'fell' if low else 'cut', d)
        return True

    def cut_at(s, j, mode='cut', fall=1):
        """Срез одного отрезка j (со всем, что на нём растёт) без попутных соседей."""
        x0, y0, x1, y1 = (float(v[j]) for v in s.geom(s.progress())[:4])
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy) + 1e-6
        mx, my, nx, ny = (x0 + x1) / 2, (y0 + y1) / 2, -dy / ln, dx / ln
        s.cut([(mx - nx * 3, my - ny * 3), (mx + nx * 3, my + ny * 3)], mode, fall, only=j)

    def crash(s, p):
        """Ствол лёг: треск, листья и щепки в стороны."""
        x0, y0, x1, y1, lx, ly = p.world()
        if len(lx) and s.cols is not None and not getattr(p, 'burn', 0):   # горящая крона листву не роняет — сгорела
            k = np.random.random(len(lx)) < .55
            n = int(k.sum())
            if n:
                s.add_particles(lx[k], ly[k] - 1, p.lc[k] * 1.1, np.random.uniform(-22, -6, n), np.random.uniform(8, 20, n),
                                np.random.uniform(-16, 16, n), None)
            p.lrel, p.lc = p.lrel[:, ~k], p.lc[~k]
        for _ in range(3):
            i = random.randrange(len(x0))
            s.burst((x0[i] + x1[i]) / 2, (y0[i] + y1[i]) / 2 - 1, 8, [WOOD, WOOD_D, (120, 96, 70)], 22, 16)
        s.gust(p.cx, p.cy, 5.0)
        s.scare(p.cx, p.cy, s.ph * .6)

    def draw_logs(s, buf):
        """Бревно лежит, обрастает мхом, потом грибами; рядом прорастают саженцы."""
        for p in s.pieces:
            if not (p.log and p.rest) or p.age < 8:
                continue
            if getattr(p, 'moss', None) is None:
                x0, y0, x1, y1, _, _ = p.world()
                rr = random.Random(int(p.cx * 7 + p.cy))
                p.moss, th = [], []
                for i in range(len(x0)):
                    r = (p.r0[i] + p.r1[i]) / 2
                    if r < .55:
                        continue
                    for _ in range(3):
                        u = rr.random()
                        p.moss.append((x0[i] + (x1[i] - x0[i]) * u, y0[i] + (y1[i] - y0[i]) * u - r * .85, rr.random(), rr.choice(MOSS)))
                    th.append((r, i))
                p.moss = p.moss[:400]
                th.sort(reverse=True)
                p.mush = [(x0[i] + (x1[i] - x0[i]) * .5 + rr.uniform(-2, 2), y0[i] + (y1[i] - y0[i]) * .5 - r - .5) for r, i in th[:5]]
            k = min(1.0, (p.age - 8) / 150)
            for X, Y, u, c in p.moss:
                if u < k * .85:
                    s.put(buf, X, Y, c)
            for i, (X, Y) in enumerate(p.mush):
                if p.age > 60 + 25 * i:
                    s.put(buf, X, Y, (232, 222, 200))
                    s.put(buf, X - 1, Y - 1, (200, 48, 40))
                    s.put(buf, X, Y - 1, (250, 244, 236))
                    s.put(buf, X + 1, Y - 1, (200, 48, 40))
            if p.age > 90 and not getattr(p, 'seeded', False) and not getattr(p, 'burn', 0):
                p.seeded = True
                for dx in (-1, 1):
                    s.try_plant(float(np.clip(p.cx + dx * (p.rad * .6 + random.uniform(4, 10)), 4, s.pw - 4)))

    def draw_stump(s, buf, g):
        st = s.stump
        if not st:
            return
        j = st['root']
        if s.rf[j] > .02:
            s.stump = None
            return
        x, y, r = float(g[0][j]), float(g[1][j]), max(1.8, float(g[4][j]))
        rx, ry = r + .3, max(1.0, r * .45)
        s.ell(buf, x, y - ry * .2, rx, ry, WOOD)
        if r >= 2.4:
            s.ell(buf, x, y - ry * .2, rx * .62, ry * .62, WOOD_D)
            s.ell(buf, x, y - ry * .2, rx * .3, ry * .3, WOOD)
        else:
            s.put(buf, x, y - ry * .2, WOOD_D)
        if s.t - st['t'] < 14:   # годовые кольца в 2–4 px не разглядеть: возраст подписью цифрами, пока свежий
            txt = str(st['years'])
            s.digits(buf, x - 2 * len(txt) + 1, y - 10, txt, WOOD_L)

    def ell(s, buf, cx, cy, rx, ry, col):
        for iy in range(int(cy - ry - 1), int(cy + ry + 2)):
            for ix in range(int(cx - rx - 1), int(cx + rx + 2)):
                if 0 <= ix < s.pw and 0 <= iy < s.ph and ((ix + .5 - cx) / rx) ** 2 + ((iy + .5 - cy) / ry) ** 2 <= 1:
                    buf[iy, ix] = col

    def line(s, buf, ax, ay, bx, by, col):
        n = max(2, int(math.hypot(bx - ax, by - ay) * 1.5))
        for k in range(n + 1):
            s.put(buf, ax + (bx - ax) * k / n, ay + (by - ay) * k / n, col)

    # ---------- семена и саженцы ----------
    def try_plant(s, x):
        tr = s.tree
        if len(s.saps) >= MAX_SAPS or s.tl is not None or not 3 < x < s.pw - 3 or abs(x - tr.cx) < 5:
            return False
        if any(abs(x - q['x']) < 7 for q in s.saps):
            return False
        sh = int(s.ph * random.uniform(.36, .5))
        return s.add_sap(x, random.randrange(10 ** 6), sh, s.t)

    def add_sap(s, x, seed, sh, t0):
        y = float(s.tree.gnd(x))
        st = Tree(max(24, sh), sh, s.preset, seed)
        s.saps.append(dict(x=x, y=y, seed=seed, sh=sh, t0=t0, dur=70 + seed % 40, tree=st, cs=None, cols=None,
                           ox=x - st.cx, oy=y - st.rooty, top=y - (st.rooty - st.top)))
        return True

    def plant_at(s, x, y):
        if y < float(s.tree.gnd(x)) - 4:
            return False
        s.try_plant(x)
        return True

    def draw_saps(s, buf):
        for q in s.saps:
            age = s.t - q['t0']
            if age < 2.5:  # семечко, потом росточек
                s.put(buf, q['x'], q['y'] - 1, (120, 84, 52))
                if age > 1.4:
                    s.put(buf, q['x'], q['y'] - 2, (110, 170, 80))
                continue
            tr = q['tree']
            G = min(1.0, (age - 2.5) / q['dur']) * tr.maxb * 1.25
            S, ox, oy = tr.S, q['ox'], q['oy']
            f = np.clip((G - S[:, 6]) / np.maximum(S[:, 7] - S[:, 6], 1e-3), 0, 1)
            m = f > 0
            a0, b0 = S[m, 0] + ox, S[m, 1] + oy
            a1, b1 = a0 + (S[m, 2] - S[m, 0]) * f[m], b0 + (S[m, 3] - S[m, 1]) * f[m]
            a0, a1 = a0 + s.wind_x(a0, b0, s.t) * .6, a1 + s.wind_x(a1, b1, s.t) * .6
            s.stroke(buf, a0, b0, a1, b1, S[m, 4], S[m, 4] + (S[m, 5] - S[m, 4]) * f[m], False)
            if q['cs'] != s.season:
                q['cs'], q['cols'] = s.season, tr.leaf_colors(s.season)
            if q['cols'] is not None:
                vis = tr.lb <= G
                lx, ly = tr.lx[vis] + ox, tr.ly[vis] + oy
                lx = lx + s.wind_x(lx, ly, s.t) * .6
                ix, iy = np.round(lx).astype(int), np.round(ly).astype(int)
                ok = (ix >= 0) & (ix < s.pw) & (iy >= 0) & (iy < s.ph)
                s.splat(buf, ix[ok], iy[ok], q['cols'][vis][ok])

    def collect(s, x, y):
        """Клик по плоду на земле: в корзину."""
        sz = 2 if s.ph >= 56 else 1
        for q in s.fr_gnd:
            if abs(q[0] - x) < 3.5 and abs(float(s.tree.gnd(q[0])) - sz - y) < 4:
                s.fr_gnd.remove(q)
                s.harv += 1
                return True
        return False

    def sprout_fruit(s, dt):
        """Плод, долго лежавший на земле, может прорасти."""
        for q in list(s.fr_gnd):
            if s.t - q[2] > 35 and random.random() < dt * .02 and len(s.saps) < MAX_SAPS:
                if s.try_plant(float(q[0])):
                    s.fr_gnd.remove(q)

    def tool_click(s, x, y):
        if s.tl is None:
            return s.collect(x, y)
        return s.collect(x, y)

    # ---------- огонь: зажигалка, распространение по дереву, пламя/искры/дым/свет (19.10.2026) ----------
    def reset_fire(s):
        tr = s.tree
        n = len(tr.par)
        s.burn_t = np.full(n, -1e9)         # когда загорелся отрезок (s.t)
        s.burn_dur = np.zeros(n)            # сколько горит
        s.burn_done = np.zeros(n, bool)
        s.fp = np.zeros((0, 8), np.float32) # частицы: x, y, vx, vy, возраст, жизнь, вид (0 искра, 1 дым, 2 пламя), размер
        s.fire_on, s.fscare, s.lit, s.gone, s.fell_t = False, 0.0, False, False, None   # gone: дерево сгорело дотла (клик по земле — новый росток)
        s.gb_t, s.gb_dur, s.gscorch = np.full(s.pw, -1e9), np.zeros(s.pw), np.zeros(s.pw)   # трава: когда загорелась колонка, сколько горит, подпалина
        parl = np.asarray(tr.parl)
        ec = np.where(parl >= 0)[0]
        s.fe_c, s.fe_p = ec, parl[ec]    # рёбра «родитель → потомок»

    def fire_alive(s, g):
        x0, y0, x1, y1, r0, r1, f = g
        return (f >= .5) & (s.rf >= 1) & (s.tree.par != -2)

    def ignite(s, j, boost=1.0):
        if s.burn_t[j] > -1e8 or s.tl is not None:
            return False
        r = float(s.tree.S[j, 4])
        s.burn_t[j] = s.t
        s.burn_dur[j] = (5.5 + r * 1.6 + random.uniform(0, 4)) * boost * (1.4 if s.trunk[j] else 1.0)
        s.scar[j] = s.gt + 400   # уголь держится долго (отсчёт остывания идёт по росту: на ×8 иначе зарастает за секунды)
        s.fire_on = True
        return True

    def ignite_near(s, x, y, rad=3.0):
        """Поднесли огонь к точке: загорается ближайший видимый отрезок или лист (лист — его отрезок)."""
        g = s.geom(s.progress())
        d, _ = s.seg_dist(g, x, y)
        d = np.where(s.fire_alive(g), d, 1e9)
        j = int(np.argmin(d))
        best, tj = float(d[j]), j
        tr = s.tree
        k = np.where(~s.lcut & (tr.lb <= s.progress()))[0] if s.cols is not None else []
        if len(k):
            px = tr.lx[k] + s.wind_x(tr.lx[k], tr.ly[k], s.t)
            dl = np.hypot(px - x, tr.ly[k] - y)
            m = int(np.argmin(dl))
            if dl[m] - .5 < best:
                best, tj = float(dl[m]) - .5, int(tr.lseg[k[m]])
        if best <= rad and s.rf[tj] >= 1:
            return s.ignite(tj)
        if y >= float(tr.gnd(min(max(x, 0), s.pw - 1))) - 4:   # поднесли к траве
            return s.ignite_ground(x)
        return False

    def erase_tree(s):
        """Дерево сгорело совсем: ни пня, ни веток, ни листьев, не отрастает; клик по земле сажает новое."""
        tr = s.tree
        s.sevt[:], s.sevb[:] = 1e9, tr.S[:, 6]
        s.update_rf()
        s.lcut[:] = True
        s.lperm[:] = True
        s.dead.update(s.deco)
        s.stump, s.fell_t, s.gone = None, None, True
        s.burn_t[:], s.burn_done[:] = -1e9, False
        s.cutv += 1
        s.gmemo = None
        for q in s.pieces:                  # лежащие брёвна тоже догорают и тают
            if q.log:
                q.log, q.age, q.burn = False, max(q.age, 5.0), s.t + 3
        s.seed_next = random.randrange(10 ** 6)
        for q in s.saps:                    # ростки от обломков тоже сгорают
            q.setdefault('burn', s.t)
        s.litter, s.fr_gnd, s.fr_fall, s.drift = [], [], [], []   # опавшая листва, плоды — всё сгорело
        s.fx = s.fy = s.fvy = s.fph = s.fvx = s.fvt = s.fz = np.zeros(0, np.float32)
        s.fc = np.zeros((0, 3), np.float32)
        s.scare(tr.cx, tr.rooty, s.ph)
        s.spawn_fp(tr.cx, tr.rooty - 1, 8, 1, vy=-9, life=(2.5, 5), size=1.6, spread=3)

    def plant_new(s):
        s.new_tree(getattr(s, 'seed_next', random.randrange(10 ** 6)))

    def ignite_ground(s, x):
        i = int(min(max(x, 0), s.pw - 1))
        if s.season == 'winter' or s.tl is not None or s.t - s.gb_t[i] < s.gb_dur[i] + 40:
            return False
        s.gb_t[i], s.gb_dur[i], s.gscorch[i] = s.t, random.uniform(3.5, 7), 1.0
        s.fire_on = True
        return True

    def spawn_fp(s, x, y, n, kind, vx=0.0, vy=0.0, life=(.5, 1.0), size=1.0, spread=1.0):
        if n <= 0:
            return
        z = max(1.0, s.ph / 50)
        a = np.zeros((n, 8), np.float32)
        a[:, 0] = x + np.random.normal(0, .6 * spread, n)
        a[:, 1] = y + np.random.normal(0, .4 * spread, n)
        a[:, 2] = vx + np.random.normal(0, 1.5 * z, n)
        a[:, 3] = vy
        a[:, 5] = np.random.uniform(*life, n)
        a[:, 6] = kind
        a[:, 7] = size * np.random.uniform(.7, 1.2, n)
        s.fp = np.concatenate([s.fp, a])[-7000:]

    def update_fire(s, dt):
        z = max(1.0, s.ph / 50)
        tr = s.tree
        if s.mouse != getattr(s, 'mouse_prev', None):
            s.mouse_prev, s.mouse_t = s.mouse, s.t
        if s.lit and s.t - getattr(s, 'mouse_t', 0.0) > 1.5:   # отпускание потерялось (мышь ушла за панель) — не держим «зажато» вечно
            s.lit = False
        if s.lighter and s.mouse is not None and s.tl is None and s.t - getattr(s, 'mouse_t', 0.0) < 3.0:   # огонёк зажигалки у курсора (мышь замерла — гаснет)
            mx, my = s.mouse
            s.spawn_fp(mx, my - 1, np.random.poisson(dt * (34 if s.lit else 16)), 2, vy=-8 * z, life=(.2, .4), size=.8, spread=.4)
            if s.lit and random.random() < dt * 3:
                s.spawn_fp(mx, my - 2, 1, 0, vy=-14 * z, life=(.6, 1.2))
            if s.lit and random.random() < dt * 6:    # огонь переходит только пока кнопка мыши зажата
                s.ignite_near(mx, my - 2, 3.0)
        gact = (s.gb_t > -1e8) & (s.t - s.gb_t < s.gb_dur)
        if gact.any():                      # огонь по траве: ползёт в стороны, тушится дождём, подпаливает землю
            wetg = max(0.0, 1 - 1.7 * s.rain) * (1 - .4 * s.wet)
            if s.rain > .3:
                kill = gact & (np.random.random(s.pw) < (s.rain - .25) * dt * 2)
                s.gb_dur[kill] = (s.t - s.gb_t)[kill]
            for i in np.where(gact)[0]:
                gy = float(tr.gnd(float(i)))
                s.spawn_fp(float(i), gy - .5, np.random.poisson(dt * 9), 2, vy=-7 * z, life=(.25, .6), size=.9, spread=.5)
                if random.random() < dt * 2:
                    s.spawn_fp(float(i), gy - 2, 1, 1, vy=-8 * z, life=(2, 4), size=1.2)
                for d in (-2, -1, 1, 2):
                    if 0 <= i + d < s.pw and random.random() < dt * 4.5 * wetg / abs(d):
                        s.ignite_ground(i + d)
            s.fscare -= dt
            if s.fscare <= 0:
                s.fscare = 1.0
                i = int(random.choice(np.where(gact)[0]))
                s.scare(float(i), float(tr.gnd(float(i))), s.ph * .25)
        if gact.any():                      # всё, что стоит на горящей траве, горит: плоды, саженцы
            sc_ = s.gscorch
            for q in [q for q in s.fr_gnd if sc_[min(max(int(q[0]), 0), s.pw - 1)] > .5]:
                s.fr_gnd.remove(q)
                s.spawn_fp(float(q[0]), float(tr.gnd(q[0])) - 1, 5, 2, vy=-9 * z, life=(.3, .7), size=1.0)
            if s.litter:                    # опавшие листья на траве сгорают вместе с ней
                s.litter = [(x, c) for x, c in s.litter if sc_[min(max(int(x), 0), s.pw - 1)] < .5]
            for q in s.saps:
                if 'burn' not in q and sc_[min(max(int(q['x']), 0), s.pw - 1)] > .5:
                    q['burn'] = s.t
        for q in list(s.saps):
            if 'burn' in q:
                n = np.random.poisson(dt * 40)
                s.spawn_fp(q['x'], q['y'] - random.uniform(0, max(2.0, q['y'] - q['top'])), n, 2, vy=-9 * z, life=(.25, .6), size=1.0, spread=.8)
                if s.t - q['burn'] > 2.8:
                    s.saps.remove(q)
                    s.spawn_fp(q['x'], q['y'] - 3, 4, 1, vy=-9 * z, life=(2, 4), size=1.3)
        for name, d in s.deco.items():      # дупло, плющ, качели, домик горят вместе с веткой
            sg = d['pts'][0][0] if name == 'ivy' else d.get('seg')
            if sg is not None and name not in s.dead and s.burn_t[sg] > -1e8 and s.t - s.burn_t[sg] > 1.5:
                s.dead.add(name)
                x0_, y0_ = float(s.tree.S[sg, 0]), float(s.tree.S[sg, 1])
                s.spawn_fp(x0_, y0_, 14, 2, vy=-10 * z, life=(.4, 1.0), size=1.5, spread=2)
                s.spawn_fp(x0_, y0_ - 2, 5, 1, vy=-9 * z, life=(2.5, 5), size=1.5, spread=2)
        s.gscorch *= math.exp(-dt / 35)
        if s.fire_on:
            g = s.geom(s.progress())
            alive = s.fire_alive(g)
            burning = (s.burn_t > -1e8) & ~s.burn_done
            age = s.t - s.burn_t
            wet = max(0.0, 1 - 1.7 * s.rain) * (1 - .4 * s.wet) * (.6 if s.season == 'winter' else 1.0)
            if s.rain > .3:   # дождь тушит
                kill = burning & (np.random.random(len(burning)) < (s.rain - .25) * dt * 1.8)
                s.burn_dur[kill] = age[kill]
            # --- переход огня по дереву: вверх быстрее, вниз медленнее, ветер помогает ---
            rate = 2.4 * (1 + .35 * s.wnow) * wet * dt
            c, p = s.fe_c, s.fe_p
            act = burning & (age < s.burn_dur)
            up = act[p] & (s.burn_t[c] < -1e8) & alive[c] & (age[p] > .6)
            dn = act[c] & (s.burn_t[p] < -1e8) & alive[p] & (age[c] > 1.2)
            for idx in (c[up & (np.random.random(len(c)) < rate)], p[dn & (np.random.random(len(c)) < rate * .45)]):
                for j in np.unique(idx):
                    s.ignite(int(j))
            # --- догорел отрезок: уголь, дымок, иногда ветка падает горящей ---
            ended = burning & (age >= s.burn_dur)
            cuts = 0
            for j in np.where(ended)[0]:
                s.burn_done[j] = True
                x1, y1 = float(g[2][j]), float(g[3][j])
                s.spawn_fp(x1, y1, 3, 1, vy=-9 * z, life=(3.0, 6.0), size=1.6)
                if cuts < 2 and alive[j] and not s.trunk[j] and random.random() < .1 and tr.par[j] != -1:
                    n0 = len(s.pieces)
                    s.cut_at(int(j), 'cut')
                    cuts += 1
                    for q in s.pieces[n0:]:
                        q.burn = s.t + 7
            # --- ствол прогорел у основания: дерево падает горящим бревном, остаётся пень ---
            ch = s.chain
            if len(ch) > 3 and s.stump is None and s.tl is None:
                b = ch[min(2, len(ch) - 1)]
                if s.burn_done[ch[0]] and s.burn_done[b] and s.rf[b] >= 1 and alive[b]:
                    xm = float(g[0][b])
                    d = random.choice((-1, 1))
                    room = {1: s.pw - xm, -1: xm}
                    if room[d] < .6 * s.gy_h() and room[-d] > room[d]:   # не хватает места — падает туда, где больше
                        d = -d
                    n0 = len(s.pieces)
                    s.cut_at(int(b), 'fell', d)
                    for q in s.pieces[n0:]:
                        q.burn = s.t + 40
                    s.fell_t = s.t
                    s.fscare = 0.0
            # --- бревно догорело — исчезает; пень, остатки и всё дерево сгорают дотла ---
            if s.fell_t is not None and s.t - s.fell_t > 44 and not act.any():
                s.erase_tree()
            # --- листья на горящих отрезках вспыхивают и сгорают ---
            k = np.where(~s.lcut & act[tr.lseg] & (tr.lb <= s.progress()))[0] if s.cols is not None else []
            k = k[np.random.random(len(k)) < dt * 3.2] if len(k) else k
            if len(k):
                lx = tr.lx[k] + s.wind_x(tr.lx[k], tr.ly[k], s.t)
                ly = tr.ly[k].astype(np.float64)
                s.lcut[k] = True
                s.lcutt[k] = s.gt + 400
                m = min(len(lx), 40)
                a = np.zeros((m * 3, 8), np.float32)
                a[:, 0], a[:, 1] = np.repeat(lx[:m], 3) + np.random.normal(0, .5, m * 3), np.repeat(ly[:m], 3) + np.random.normal(0, .4, m * 3)
                a[:, 2], a[:, 3] = np.random.normal(0, 1.5 * z, m * 3), -10 * z
                a[:, 5], a[:, 6], a[:, 7] = np.random.uniform(.35, .8, m * 3), 2, 1.3 * np.random.uniform(.7, 1.2, m * 3)
                s.fp = np.concatenate([s.fp, a])[-7000:]
                if random.random() < .5:
                    s.spawn_fp(float(lx[0]), float(ly[0]), 1, 0, vy=-9 * z, life=(1, 2.2))
            # --- пламя вдоль горящих отрезков ---
            ia = np.where(act & alive)[0]
            if len(ia):
                fl = np.clip((np.hypot(g[2][ia] - g[0][ia], g[3][ia] - g[1][ia]) + g[5][ia]) * .35 + .3, .3, 3.0)
                ramp = np.clip(age[ia] / 1.2, 0, 1) * np.clip((s.burn_dur[ia] - age[ia]) / 1.5 + .3, 0, 1)   # разгорается и затухает
                nn = np.random.poisson(dt * 17 * fl * ramp)
                sid = np.repeat(np.arange(len(ia)), nn)
                if len(sid):
                    j = ia[sid]
                    u = np.random.random(len(sid))
                    px = g[0][j] + (g[2][j] - g[0][j]) * u
                    py = g[1][j] + (g[3][j] - g[1][j]) * u
                    m = len(sid)
                    a = np.zeros((m, 8), np.float32)
                    a[:, 0], a[:, 1] = px + np.random.normal(0, .5, m), py
                    a[:, 2] = np.random.normal(0, 1.2 * z, m) + s.wnow * 2.2
                    a[:, 3] = -np.random.uniform(7, 15, m) * z
                    a[:, 5] = np.random.uniform(.35, .9, m) * (.7 + .3 * fl[sid])
                    a[:, 6] = 2
                    a[:, 7] = np.clip(.8 + g[5][j] * .5, .8, 2.2)
                    s.fp = np.concatenate([s.fp, a])[-7000:]
                    sm = np.where(np.random.random(m) < .3)[0]
                    if len(sm):
                        s.spawn_fp(float(px[sm[0]]), float(py[sm[0]]) - 2, len(sm), 1, vy=-11 * z, life=(2.5, 5.5), size=1.5)
                    sp = np.where(np.random.random(m) < .06)[0]
                    if len(sp):
                        s.spawn_fp(float(px[sp[0]]), float(py[sp[0]]) - 1, len(sp), 0, vy=-17 * z, life=(.8, 2.0))
                s.fscare -= dt
                if s.fscare <= 0:
                    s.fscare = 1.0
                    j = int(random.choice(ia))
                    s.scare(float(g[2][j]), float(g[3][j]), s.ph * .25)
            elif not act.any() and not len(s.fp) and not gact.any():
                s.fire_on = False
                if not s.gone and alive.any() and s.burn_done[alive].mean() > .6:   # выгорело почти всё, но не упало — догорает дотла
                    s.erase_tree()
                s.burn_t[:], s.burn_done[:] = -1e9, False   # остыло: дерево снова можно поджечь
        # --- горящие куски на земле ---
        for q in s.pieces:
            if q.log and getattr(q, 'burn', 0) and q.burn <= s.t and q.rest:   # горящее бревно догорело: тает
                q.log, q.age = False, max(q.age, 8.0)
            if getattr(q, 'burn', 0) > s.t:
                x0, y0, x1, y1, lx, ly = q.world()
                if q.rest and random.random() < dt * 1.5:
                    s.ignite_ground(q.cx + random.uniform(-q.rad, q.rad))
                for i in random.sample(range(len(x0)), min(len(x0), 3)):
                    s.spawn_fp(float((x0[i] + x1[i]) / 2), float((y0[i] + y1[i]) / 2), int(random.random() < dt * 40), 2, vy=-8 * z, life=(.3, .7), size=1.0)
        # --- движение частиц ---
        P = s.fp
        if not len(P):
            return
        P[:, 4] += dt
        t = P[:, 4] / P[:, 5]
        fl, sm, sp = P[:, 6] == 2, P[:, 6] == 1, P[:, 6] == 0
        P[:, 2] += (s.wnow * 1.6 * z) * dt * (fl | sm)
        P[sm, 2] *= math.exp(-dt * .5)
        P[sm, 3] *= math.exp(-dt * .35)
        P[sp, 3] += 9 * z * dt            # искры сначала летят вверх, потом оседают
        P[sp, 2] += np.random.normal(0, 5 * z, int(sp.sum())) * dt
        P[fl, 3] *= math.exp(-dt * .6)
        P[:, 0] += P[:, 2] * dt
        P[:, 1] += P[:, 3] * dt
        gy = tr.gnd(np.clip(P[:, 0], 0, s.pw - 1))
        land = sp & (P[:, 1] > gy)
        for x in P[land, 0][:6]:             # искра упала в траву
            if random.random() < .12 * max(0.0, 1 - 1.7 * s.rain):
                s.ignite_ground(float(x))
        s.fp = P[(t < 1) & ~land]

    def draw_fire_fx(s, buf):
        if s.gscorch.max() > .03:            # выжженная трава темнеет и медленно отрастает
            xs = np.where(s.gscorch > .03)[0]
            gg = s.tree.gnd(xs.astype(np.float32))
            for dy, w in ((-1, .5), (0, .75), (1, .55), (2, .3)):
                yy = np.clip(np.round(gg + dy).astype(int), 0, s.ph - 1)
                buf[yy, xs] *= (1 - w * s.gscorch[xs])[:, None] * np.array((1, 1, 1.05), np.float32)
        P = s.fp
        if not len(P):
            return
        pw, ph = s.pw, s.ph
        t = np.clip(P[:, 4] / P[:, 5], 0, 1)
        ph_ = P[:, 0] * 1.7 + P[:, 5] * 9
        fx = P[:, 0] + np.sin(P[:, 4] * 19 + ph_) * .55 * P[:, 7] * (P[:, 6] == 2)
        ix, iy = np.round(fx).astype(int), np.round(P[:, 1]).astype(int)
        ok = (ix >= 0) & (ix < pw) & (iy >= 1) & (iy < ph)
        # дым: серый, полупрозрачный, растёт
        sm = ok & (P[:, 6] == 1)
        if sm.any():
            a = (np.sin(np.pi * t[sm]) ** 1.1 * .36)[:, None]
            night = float(s.lt_night)
            col = np.array((92, 90, 96), np.float32) * (1 - .45 * night)
            for dx, dy, k in ((0, 0, 1), (1, 0, .6), (0, -1, .6), (-1, 0, .6), (1, -1, .35), (-1, -1, .35), (0, 1, .35)):
                xx, yy = np.clip(ix[sm] + dx, 0, pw - 1), np.clip(iy[sm] + dy, 0, ph - 1)
                buf[yy, xx] = buf[yy, xx] * (1 - a * k) + col * a * k
        # пламя и искры: аддитивно, цвет по возрасту (белое ядро → жёлтый → оранжевый → красный → тёмный)
        STOPS = np.array([(0, 255, 236, 170), (.2, 255, 186, 60), (.5, 245, 104, 24), (.8, 200, 44, 14), (1, 70, 14, 8)], np.float32)
        def ramp(tt):
            return np.stack([np.interp(tt, STOPS[:, 0], STOPS[:, c]) for c in (1, 2, 3)], 1)
        fl = ok & (P[:, 6] == 2)
        if fl.any():
            tt = t[fl]
            col = ramp(tt)
            al = (np.clip(1.15 - tt ** 1.6, 0, 1) * np.clip(P[fl, 7] * .85, .55, 1.5))[:, None]
            for dy, k in ((0, 1.0), (-1, .65), (-2, .3)):   # язык: ядро и вытянутый хвост вверх
                yy = np.clip(iy[fl] + dy, 0, ph - 1)
                cc = col * (np.array((1, .8, .55), np.float32) if dy else 1)
                lum = buf[yy, ix[fl]].mean(-1, keepdims=True) / 255
                np.add.at(buf, (yy, ix[fl]), cc * al * k * .5 * (1 - .75 * np.clip(lum, 0, 1)))
            if (P[fl, 7] > 1.4).any():                       # крупное пламя шире
                w = fl & (P[:, 7] > 1.4)
                for dx in (-1, 1):
                    xx = np.clip(ix[w] + dx, 0, pw - 1)
                    np.add.at(buf, (iy[w], xx), ramp(t[w]) * (np.clip(1.15 - t[w] ** 1.6, 0, 1) * .45)[:, None] * (1 - .75 * np.clip(buf[iy[w], xx].mean(-1, keepdims=True) / 255, 0, 1)))
        sp = ok & (P[:, 6] == 0)
        if sp.any():
            tt = t[sp]
            blink = .65 + .35 * np.sin(P[sp, 4] * 40 + P[sp, 0])
            np.add.at(buf, (iy[sp], ix[sp]), ramp(tt * .85) * (np.clip(1.2 - tt, 0, 1) * blink)[:, None] * (1 - .6 * np.clip(buf[iy[sp], ix[sp]].mean(-1, keepdims=True) / 255, 0, 1)))
        # тепловое свечение: тёплый свет вокруг нескольких случайных языков
        if fl.any():
            idx = np.where(fl)[0]
            for i in np.random.choice(idx, min(len(idx), 14), replace=False):
                R = max(5, int(s.ph * .07))
                x, y = ix[i], iy[i] - 1
                x0, x1, y0, y1 = max(0, x - R), min(pw, x + R + 1), max(0, y - R), min(ph, y + R + 1)
                if x1 <= x0 or y1 <= y0:
                    continue
                X, Y = np.arange(x0, x1)[None, :], np.arange(y0, y1)[:, None]
                w = np.clip(1 - np.hypot(X - x, (Y - y) * 1.2) / R, 0, 1) ** 2 * (1 - t[i]) * 14
                buf[y0:y1, x0:x1] += w[..., None] * np.array((255, 120, 40), np.float32) * .05

    # ---------- молния в дерево ----------
    def strike(s):
        """Удар в верхушку: ветка ломается или обгорает; на коре шрам, он потом зарастает."""
        tr = s.tree
        g = s.geom(s.progress())
        x0, y0, x1, y1, r0, r1, f = g
        ok = np.where((f >= 1) & (tr.par != -2) & (s.rf >= 1) & ~s.perm)[0]
        if not len(ok) or not s.grown() or s.tl is not None:
            return None
        j = int(random.choice(ok[np.argsort(y1[ok])[:max(3, len(ok) // 10)]]))
        x, y = float(x1[j]), float(y1[j])
        px, py = x + random.uniform(-6, 6), 0.0
        pts = [(px, py)]
        while py < y - 4:
            py += random.uniform(3, 6)
            px += (x - px) * .25 + random.uniform(-3, 3)
            pts.append((px, min(py, y)))
        pts.append((x, y))
        s.bolt, s.flash = (s.t, pts), 1.0
        pj = int(tr.parl[j])
        if pj >= 0:
            s.scar[pj] = s.gt
        s.scar[j] = s.gt
        if random.random() < .5:
            s.cut_at(j, 'cut')
            s.fire.append(dict(x=float(x0[j]), y=float(y0[j]), t0=s.t, dur=6.0))
        else:
            near = np.where(~s.lcut & (np.hypot(tr.lx - x, tr.ly - y) < 8) & (s.progress() >= tr.lb))[0]
            if len(near) and s.cols is not None:
                s.drop_leaves(near, tr.lx[near], tr.ly[near], 0.0)
            s.ignite(j, 1.5)
        s.burst(x, y, 10, [(255, 190, 70), (255, 120, 40), (60, 50, 44)], 22, 18)
        return j

    def draw_fire(s, buf):
        s.fire = [q for q in s.fire if s.t - q['t0'] < q['dur']]
        for q in s.fire:
            k = 1 - (s.t - q['t0']) / q['dur']
            for i in range(4):
                if random.random() < .4 + .5 * k:
                    s.put(buf, q['x'] + math.sin(s.t * 17 + i * 2) * .9, q['y'] - i * .9 - 1,
                          ((255, 90, 30), (255, 150, 40), (255, 215, 90), (255, 240, 170))[i], .9)

    def draw_scars(s, buf, g):
        x0, y0, x1, y1, r0, r1, f = g
        bark = s.bark_col()
        js = np.where((s.scar > -1e8) & (f > 0))[0]
        if len(js):
            u = (s.gt - s.scar[js]) / 220
            q = np.clip(np.floor(u * 8).astype(int), 0, 8)   # цвет угля → коры ступенями: один вызов на ступень, а не на отрезок
            for b in np.unique(q[u < 1]):
                sl = js[(q == b) & (u < 1)]
                c = np.array(CHAR, np.float32) * (1 - (b + .5) / 8) + bark * ((b + .5) / 8)
                s.stroke(buf, x0[sl], y0[sl], x1[sl], y1[sl], r0[sl], r1[sl], False, c)
        par = s.tree.par
        for j in np.where(s.perm & (par >= 0) & ~s.perm[np.maximum(par, 0)])[0]:  # свежий срез формы — светлая точка
            if f[par[j]] >= 1:
                s.put(buf, x0[j], y0[j], WOOD_L)

    # ---------- декор: дупло, плющ, качели, домик ----------
    def build_deco(s):
        tr = s.tree
        s.deco, s.chain, s.trunk = {}, [], np.zeros(len(tr.par), bool)
        S, par, n = tr.S, tr.parl, len(tr.par)
        kids = [[] for _ in range(n)]
        for j, pj in enumerate(par):
            if pj >= 0:
                kids[pj].append(j)
        j = next((i for i, pj in enumerate(par) if pj == -1), None)
        while j is not None:
            s.chain.append(j)
            j = max(kids[j], key=lambda k: S[k, 4]) if kids[j] else None
        s.trunk[s.chain] = True
        if tr.P.get('conifer'):   # у сосны ствол нужен топору, а декора нет
            return
        rng = random.Random(s.seed * 31 + 7)
        roll = [rng.random() for _ in range(4)]
        L = len(s.chain)
        d = s.deco
        d['hollow'] = dict(on=roll[0] < .6, seg=s.chain[int(L * rng.uniform(.14, .3))], side=rng.choice((-1, 1)), res=rng.choice(('owl', 'squirrel')))
        m = max(2, int(L * .45))   # выше крона всё равно закрывает ствол
        d['ivy'] = dict(on=roll[1] < .5, pts=[(s.chain[i], u, i * 1.1 + u * 3) for i in range(m) for u in (0, .33, .66)])
        h = s.gy_h()
        cand = [i for i in range(n) if par[i] != -2 and not s.trunk[i] and abs(S[i, 3] - S[i, 1]) <= abs(S[i, 2] - S[i, 0]) * .7
                and abs(S[i, 2] - S[i, 0]) >= .5 and S[i, 4] >= .4 and abs((S[i, 0] + S[i, 2]) / 2 - tr.cx) > 3
                and .3 <= (tr.rooty - (S[i, 1] + S[i, 3]) / 2) / h <= .78]
        cand.sort(key=lambda i: -S[i, 4])
        top = cand[:8]
        if top:
            i = rng.choice(top)
            ym = (S[i, 1] + S[i, 3]) / 2
            room = float(tr.gnd((S[i, 0] + S[i, 2]) / 2)) - ym - 3
            if room >= 6:
                d['swing'] = dict(on=roll[2] < .4, seg=i, u=.5, len=min(room, s.ph * .16), ph=rng.uniform(0, 6))
        big = [i for i in cand if S[i, 4] >= .55 and i not in [v['seg'] for v in d.values() if 'seg' in v]]
        if big:
            d['house'] = dict(on=roll[3] < .3, seg=rng.choice(big[:5]), u=.5, side=0)
        elif L > 6:
            d['house'] = dict(on=roll[3] < .3, seg=s.chain[int(L * .42)], u=.5, side=rng.choice((-1, 1)))

    def gy_h(s):
        return max(1.0, s.tree.rooty - s.tree.top)

    def deco_show(s, name, need):
        d = s.deco.get(name)
        if not d or s.deco_mode == 'none' or name in s.dead:
            return None
        if s.deco_mode == 'all' or (d['on'] and s.gt - s.grow_time * 1.12 > need):
            return d
        return None

    def draw_deco(s, buf):
        if not s.deco or s.deco_mode == 'none':
            return
        g = s.geom(s.progress())
        x0, y0, x1, y1, r0, r1, f = g

        def pt(j, u):
            return x0[j] + (x1[j] - x0[j]) * u, y0[j] + (y1[j] - y0[j]) * u, r0[j] + (r1[j] - r0[j]) * u
        age = s.gt - s.grow_time * 1.12
        night = s.lt_night > .5
        d = s.deco_show('ivy', 0)
        if d:
            k = 1.0 if s.deco_mode == 'all' else min(1.0, age / 240)
            pal = SEASONS[s.season]['pal']
            c1 = np.array((120, 132, 112) if pal is None else (206, 84, 36) if s.season == 'autumn' else (84, 176, 66), np.float32)
            c2 = np.array((170, 182, 160) if pal is None else (246, 176, 56) if s.season == 'autumn' else (170, 232, 96), np.float32)
            for seg, u, ph in d['pts'][:int(len(d['pts']) * k)]:
                if f[seg] < 1:
                    continue
                X, Y, R = pt(seg, u)
                off = math.sin(ph) * (R + .5)
                s.put(buf, X + off, Y, c1)
                s.put(buf, X + off, Y + 1, c1)
                if int(ph * 5) % 3 == 0:
                    sg = 1 if off > 0 else -1
                    s.put(buf, X + off + sg, Y - 1, c2)
                    s.put(buf, X + off + 2 * sg, Y, c2)
        d = s.deco_show('hollow', 120)
        if d and f[d['seg']] >= 1:
            X, Y, R = pt(d['seg'], .5)
            if R >= .8:
                rx = max(1.0, R * .5)
                cx_ = X + d['side'] * R * .3
                s.ell(buf, cx_, Y, rx, rx * 1.4, (22, 14, 10))
                if d['res'] == 'owl' and night and int(s.t * .8) % 9:
                    s.put(buf, cx_ - .5, Y - .5, (255, 214, 90))
                    s.put(buf, cx_ + .5, Y - .5, (255, 214, 90))
                elif d['res'] == 'squirrel' and not night and (s.t % 26) < 5:
                    s.put(buf, cx_, Y + .5, (176, 116, 62))
                    s.put(buf, cx_, Y - .5, (176, 116, 62))
                    s.put(buf, cx_ + .6 * d['side'], Y - .5, (20, 14, 10))
        d = s.deco_show('swing', 200)
        if d:
            j = d['seg']
            if f[j] < 1:
                s.deco_fall('swing', *pt(j, d['u'])[:2])
            else:
                X, Y, R = pt(j, d['u'])
                a = .12 * math.sin(1.7 * s.t + d['ph']) + .05 * s.wnow * math.sin(.9 * s.t)
                L = max(4.0, min(d['len'], float(s.tree.gnd(X)) - Y - 3))
                ends = []
                for sg in (-1, 1):
                    ax, ay = X + sg * 2.0, Y + R
                    bx, by = ax + L * math.sin(a), ay + L * math.cos(a)
                    s.line(buf, ax, ay, bx, by, (236, 220, 176))
                    ends.append((bx, by))
                s.line(buf, ends[0][0], ends[0][1], ends[1][0], ends[1][1], (150, 104, 64))
                s.line(buf, ends[0][0], ends[0][1] + 1, ends[1][0], ends[1][1] + 1, (118, 80, 50))
                s.put(buf, (ends[0][0] + ends[1][0]) / 2, (ends[0][1] + ends[1][1]) / 2 + 1, (120, 80, 50))
        d = s.deco_show('house', 300)
        if d:
            j = d['seg']
            if f[j] < 1:
                s.deco_fall('house', *pt(j, d['u'])[:2])
            else:
                X, Y, R = pt(j, d['u'])
                w = int(max(7, s.ph * .1))
                h = int(w * .75)
                X = X + d['side'] * (w / 2 + R)
                by = int(Y - R)
                bx = int(X - w / 2)
                if by - h - 5 > 0:
                    for iy in range(h):
                        for ix in range(w):
                            if 0 <= bx + ix < s.pw and 0 <= by - h + iy < s.ph:
                                buf[by - h + iy, bx + ix] = (176, 126, 80) if (ix + iy) % 3 else (150, 106, 66)
                    # крыша
                    for k in range(h // 2 + 2):
                        for ix in range(w // 2 - (h // 2 + 2 - k) - 1, w // 2 + (h // 2 + 2 - k) + 2):
                            yy = by - h - 1 - k
                            if 0 <= bx + ix < s.pw and 0 <= yy < s.ph:
                                buf[yy, bx + ix] = (150, 56, 44)
                    for ix in range(w + 2):
                        s.put(buf, bx - 1 + ix, by, (118, 82, 52))
                    s.ell(buf, bx + w * .3, by - 1.5, 1.0, 1.6, (84, 56, 36))
                    win = (255, 226, 130) if night else (130, 170, 200)
                    s.put(buf, bx + w * .7, by - h * .6, win)
                    s.put(buf, bx + w * .7 + 1, by - h * .6, win)

    def deco_fall(s, name, x, y):
        s.dead.add(name)
        s.burst(x, y, 12, [(176, 126, 80), (150, 56, 44), (118, 82, 52)], 20, 10)

    def draw_hud(s, buf):
        if s.harv <= 0:
            return
        x, y = 3, 3
        for dx, dy, c in ((0, 1, (200, 36, 40)), (1, 1, (200, 36, 40)), (0, 2, (200, 36, 40)), (1, 2, (200, 36, 40)), (1, 0, (90, 150, 60))):
            s.put(buf, x + dx, y + dy, c)
        s.digits(buf, x + 4, y, str(s.harv), (250, 244, 232))

    def digits(s, buf, x, y, txt, col):
        for ch in txt:
            for i, b in enumerate(DIGITS[ch]):
                if b == '1':
                    s.put(buf, x + i % 3 + 1, y + i // 3 + 1, (0, 0, 0), .55)
                    s.put(buf, x + i % 3, y + i // 3, col)
            x += 4


class Scene(Life):
    def __init__(s, pw, ph, bg, preset='oak', season='autumn', seed=None, wind=1.0, grow_time=14.0, weather='clear', tod='auto', mem=None):
        s.pw, s.ph, s.bg = pw, ph, bg
        s.sharp = 0   # чёткость 0..SHARP_MAX: локальный контраст, снятие вуали, отрыв дерева от фона (0 — как раньше)
        s.mem, s.tool, s.deco_mode, s.harv, s.lighter = mem or {}, 'cut', 'auto', 0, False   # mem: {(вид, seed): [срезано «формой»]}
        s.preset, s.season, s.wind = preset, season, wind
        s.grow_time = grow_time
        s.seed = seed if seed is not None else random.randrange(10 ** 6)
        s.noise = np.random.default_rng(7).uniform(.9, 1.1, (ph, pw)).astype(np.float32)
        s.gx = (np.arange(pw, dtype=np.float32) + .5)[None, :]
        s.gyy = (np.arange(ph, dtype=np.float32) + .5)[:, None]
        s.gusts, s.mouse, s.mdir = [], None, 1
        s.drag, s.slash, s.pieces = None, [], []
        s.gt, s.spd, s.cutv, s.lacc, s.gmemo = 0.0, 3, 0, 0.0, None
        s.rmode = False  # режим «случайно»: каждое новое дерево с новыми видом, сезоном, погодой и ветром
        s.wx_name, s.tod_name = weather, tod
        s.rain = s.fog = s.storm = s.wet = 0.0
        s.wnow = wind
        s.lt_tint, s.lt_night = np.ones(3, np.float32), 0.0
        s.birds, s.bflies, s.bird_timer, s.bf_timer = [], [], 6.0, 2.0
        s.rx = s.ry = s.rv = np.zeros(0, np.float32)
        s.splash, s.flash, s.bolt, s.next_flash = [], 0.0, None, 8.0
        s.bd_name, s.tl, s.tl_saved = 'rand', None, None   # фон; таймлапс (секунды с начала или None)
        s.clock = None                        # часы суток в бесконечном режиме (None — по реальным)
        s.owl = s.squirrel = s.deer = s.rb = s.aurora = s.shower = s.nest = None
        s.meteors, s.gc, s.gc_t, s.aur_t, s.nest_t = [], {}, {}, 30.0, 4.0
        s.owl_t, s.sq_t, s.deer_t, s.met_t = 8.0, random.uniform(10, 30), random.uniform(40, 100), random.uniform(10, 30)
        s.was_rain, s.pud, s.snowd, s.sun = False, 0.0, 0.0, None
        rg = random.Random(5)
        s.clouds = [dict(x=rg.uniform(0, pw), y=rg.uniform(.07, .30) * ph, w=rg.uniform(.18, .34) * pw, h=rg.uniform(.04, .075) * ph,
                         v=rg.uniform(1.2, 3.2)) for _ in range(5)]
        s.new_tree()

    def new_tree(s, seed=None):
        if seed is not None:
            s.seed = seed
        s.tree = Tree(s.pw, s.ph, s.preset, s.seed)
        old_t = getattr(s, 't', 0.0)
        s.t = s.gt = s.hold = 0.0
        # всё, что хранит время начала по s.t, надо сбросить вместе с ним, иначе «возраст» отрицательный и оно не гаснет
        s.splash, s.bolt, s.gusts, s.flash = [], None, [], 0.0
        s.meteors, s.gc, s.nest = [], {}, None
        # долгие события (сияние, метеоритный дождь, радуга) переживают смену дерева: сдвигаем время начала на прошедшее
        s.aurora = (s.aurora[0] - old_t, s.aurora[1]) if s.aurora else None
        s.shower = s.shower - old_t if s.shower is not None else None
        s.rb = (s.rb[0] - old_t, s.rb[1]) if s.rb else None
        n, N = len(s.tree.par), len(s.tree.lx)
        s.sevt = np.full(n, -1e9)                 # когда срезан отрезок (отрастает от пня)
        s.sevb = np.zeros(n)                      # длина вдоль ветки, с которой начинается отрастание
        s.rrate = s.tree.maxb / s.grow_time * .35 # отрастает медленнее, чем растёт молодое дерево
        s.rf = np.ones(n, np.float32)             # доля отрасти отрезка (1 — целый)
        s.sev = np.zeros(n, bool)                 # отрезок ещё не отросший
        s.lcut = np.zeros(N, bool)                # листья, которых сейчас нет
        s.lcutt = np.full(N, -1e9)                # когда сорван
        s.lborn = np.full(N, -1e9)                # когда отрос заново (молодой лист светлее)
        s.ldel = np.random.default_rng(s.seed + 5).uniform(4, 24, N)  # через сколько отрастает
        P = s.tree.P
        s.tree.sup0 = s.support_dist(np.arange(N), np.zeros(n, bool))
        s.lperm = s.tree.sup0 > (1.3 * P['leafR'] * s.ph * max(P['aspect']) if P.get('conifer') else 5 * P['reach'] * s.ph * max(P['aspect']))  # одиночки далеко от веток не рисуем
        s.lcut |= s.lperm
        s.pieces, s.drag, s.slash, s.birds, s.bflies, s.gmemo = [], None, [], [], [], None
        s.owl = s.squirrel = s.deer = None
        s.reset_life()
        s.build_deco()
        s.apply_memory()
        s.build_extras()
        s.restyle()

    def build_extras(s):
        """Что зависит от дерева и панели: места плодов, лужи, трава, цветы, грибы."""
        tr, ph, pw = s.tree, s.ph, s.pw
        rng = np.random.default_rng(s.seed + 9)
        ok = np.where(~s.lperm)[0]
        n = min(len(ok), max(5, pw // (3 if s.preset == 'apple' else 5)))
        s.fr_i = rng.choice(ok, n, replace=False) if n else np.zeros(0, int)
        s.fr_off = rng.uniform(0, 150, n)   # через сколько секунд после взросления плод начинает наливаться
        s.puds = []
        for _ in range(3):
            x = rng.uniform(.08, .92) * pw
            g = float(tr.gnd(x))
            if ph - g > 6:
                s.puds.append((x, g + 2 + rng.uniform(.1, .9) * (ph - g - 4), rng.uniform(.05, .11) * pw + 3, rng.uniform(1.0, 1.7)))
        s.gr_x = np.minimum(np.arange(0, pw, 2) + rng.integers(0, 2, len(range(0, pw, 2))), pw - 1).astype(np.float32)
        hmax = max(2, round(ph * .03))
        s.gr_h = rng.integers(1, hmax + 1, len(s.gr_x))
        s.gr_c = rng.uniform(.85, 1.25, len(s.gr_x)).astype(np.float32)
        s.gr_fl = rng.random(len(s.gr_x)) < .2
        s.gr_fc = rng.integers(0, len(FLOWERS), len(s.gr_x))
        s.mush = [(x, rng.uniform(0, 80)) for x in rng.uniform(.06, .94, 6) * pw if abs(x - tr.cx) > 4]

    def restyle(s):
        s.fr_fall, s.fr_gnd, s.drift = [], [], []
        s.snowd = .2 if s.season == 'winter' else 0.0
        s.cols = s.tree.leaf_colors(s.season)
        s.base = s.make_base()
        s.build_backdrop()
        s.fx = s.fy = s.fvy = s.fph = s.fvx = s.fvt = s.fz = np.zeros(0, np.float32)
        s.fc = np.zeros((0, 3), np.float32)
        s.litter = []

    def make_base(s):
        cfg = SEASONS[s.season]
        bg = np.array(s.bg, np.float32)
        img = np.empty((s.ph, s.pw, 3), np.float32)
        img[:] = bg
        T = s.tree
        d2 = ((s.gx - T.cx) ** 2 + (s.gyy - (T.gy - .45 * s.ph)) ** 2) / (.36 * s.ph) ** 2
        img += np.exp(-d2)[..., None] * np.array(cfg['glow'], np.float32) * .6
        rng = np.random.default_rng(3)  # звёзды рисуются только ночью (draw_sky)
        n = max(8, s.pw * s.ph // 300)
        s.stars = (rng.integers(0, s.pw, n), rng.integers(0, int(s.ph * .6), n), rng.uniform(.4, 1, n), rng.uniform(0, 6.28, n))
        g = T.gnd(s.gx)
        cov = np.clip(s.gyy + .5 - g, 0, 1)
        s.gmask = cov[..., None].astype(np.float32)
        depth = np.clip((s.gyy - g) / max(1, s.ph - T.gy + T.mound), 0, 1) ** .6
        top, bot = (np.array(c, np.float32) for c in cfg['ground'])
        col = (top + (bot - top) * depth[..., None]) * s.noise[..., None]
        img = img * (1 - cov[..., None]) + col * cov[..., None]
        return img


    # ---------- фон ----------
    def build_backdrop(s):
        """Слои за деревом: цвет, непрозрачность и глубина (0 — далеко, 1 — близко); дым, окна и лопасти рисуются в кадре."""
        s.bd = None
        rng = np.random.default_rng(s.seed + 31)
        kind = s.bd_name
        if kind == 'rand':
            kind = BD_KINDS[int(rng.integers(len(BD_KINDS)))]
        s.bd_kind = kind
        if kind == 'none':
            return
        tr, pw, ph = s.tree, s.pw, s.ph
        gy, win = float(tr.gy), s.season == 'winter'
        lake = kind == 'lake'
        mount = kind == 'mountains' or (lake and rng.random() < .5)
        yh = gy - (.12 + .04 * rng.random()) * ph if lake else gy - 1      # линия горизонта: у озера над землёй полоса воды
        col = np.zeros((ph, pw, 3), np.float32)
        al = np.zeros((ph, pw), np.float32)
        dep = np.zeros((ph, pw), np.float32)
        base = np.array(BD_HILL[s.season], np.float32)
        L = int(rng.integers(3, 5)) if mount else int(rng.integers(2, 4))
        tops = []
        kern = np.ones(9) / 9

        def smooth1(v):
            return np.convolve(np.pad(v, 4, mode='edge'), kern, 'valid')
        for i in range(L):
            d = i / max(1, L - 1)
            amp = (.5 - .2 * d if mount else .14 - .045 * d) * ph * (.85 + .3 * rng.random())
            h = ridge(rng, pw, 5 if mount else 3, smooth=not mount, ridged=mount)
            ytop = yh - 2 - amp * (.25 + .75 * h) - (1 - d) * .02 * ph
            tops.append(ytop)
            sl = smooth1(np.gradient(ytop)) if len(ytop) > 1 else np.zeros(len(ytop))
            lit = np.clip(-sl / (.9 if mount else .35), -1, 1)[None, :, None]       # свет слева: склон, поднимающийся вправо, освещён
            dy = s.gyy - ytop[None, :]
            m = dy >= 0
            n1 = rng.random(pw) * 6
            if mount:
                rock = np.array((86, 92, 118), np.float32) * (.86 + .2 * d)
                c = rock * (1 + .38 * lit) + np.array((18, 8, 0), np.float32) * np.clip(lit, 0, 1)
                fac = np.sin(s.gx * .5 + dy * .75 + n1[None, :])[..., None]          # диагональные борозды породы
                c = c * (1 + .085 * fac * (.5 + d))
                c = c * (1.12 - .3 * np.clip(dy / amp, 0, 1)[..., None])
                sline = amp * ((.26 if not win else .4) + .2 * smooth1(rng.random(pw)))[None, :] * (1 + .25 * np.sin(s.gx * .7 + dy * .3))
                sn = np.clip((sline - dy) / 1.4, 0, 1)[..., None]
                scol = np.array((238, 244, 252), np.float32) * (.93 + .07 * lit) * (1 - .1 * np.clip(-lit, 0, 1)) + np.array((-34, -26, -6), np.float32) * np.clip(-lit, 0, 1)
                c = c * (1 - sn) + scol * sn
            else:
                tone = base * (.8 + .24 * d) * np.array((1, 1.02 - .03 * i, 1), np.float32)
                c = tone * (1 + .2 * lit)
                c = c * (1.1 - .2 * np.clip(dy / (.14 * ph), 0, 1)[..., None])
                c = c * (1 + .045 * np.sin(s.gx * .12 + dy * .45 + i * 2)[..., None] * (.3 + d))   # поля полосами
                c = np.where(dy[..., None] < 1.2, c * 1.13, c)                                         # светлая кромка гребня
            c = np.broadcast_to(c, (ph, pw, 3))
            col[m] = c[m]
            al[m] = 1
            dep[m] = .12 + .55 * d
        near = tops[-1]
        bd = dict(lights=[], smoke=[], mill=None, water=None)

        def spot(lo, hi):
            for _ in range(20):
                x = rng.uniform(lo, hi) * pw
                if abs(x - tr.cx) > .3 * pw:
                    return int(x)
            return int(rng.choice([.08, .92]) * pw)

        def rect(x0, y0, x1, y1, c, d=.8):
            x0, x1, y0, y1 = max(0, int(x0)), min(pw, int(x1)), max(0, int(y0)), min(ph, int(y1))
            if x1 > x0 and y1 > y0:
                col[y0:y1, x0:x1] = c
                al[y0:y1, x0:x1] = 1
                dep[y0:y1, x0:x1] = d

        def sh(c, k):
            return tuple(float(min(255, v * k)) for v in c)

        def pine(x, yb, hgt, d=.72):
            """Ёлочка: тёмный треугольник, свет слева, зимой снег на лапах."""
            g = (34 + 16 * rng.random(), 84 + 24 * rng.random(), 54 + 10 * rng.random())
            if s.season == 'autumn' and rng.random() < .35:
                g = (176, 104, 40)
            rect(x, yb - 1, x + 1, yb + 1, (70, 50, 38), d)
            for r in range(hgt):
                hw_ = int(1 + r * .55 * (3 / max(3, hgt)) * 1.9) // 2 + (1 if r > 1 else 0)
                y_ = yb - hgt + r
                snow_ = win and r % 3 == 0
                rect(x - hw_, y_, x + 1, y_ + 1, (232, 238, 246) if snow_ else sh(g, 1.18), d)
                rect(x + 1, y_, x + 1 + hw_, y_ + 1, (214, 222, 236) if snow_ else sh(g, .82), d)

        def house(hx, hw, hh, gyh, wall, roof, big=True):
            roof_h = hw // 2 + 1
            rect(hx, gyh - hh, hx + hw, gyh + 1, wall)                               # стена
            rect(hx, gyh - 1, hx + hw, gyh + 1, sh(wall, .72))                       # цоколь
            rect(hx + hw - 2, gyh - hh, hx + hw, gyh - 1, sh(wall, .86))             # тень от правого края
            for r in range(roof_h + 1):                                              # двускатная крыша с карнизом
                xa, xb = hx - 1 + r, hx + hw + 1 - r
                y_ = gyh - hh - 1 - r
                mid = (xa + xb) // 2
                rect(xa, y_, mid + 1, y_ + 1, sh(roof, 1.14))
                rect(mid + 1, y_, xb, y_ + 1, sh(roof, .8))
            rect(hx - 1, gyh - hh, hx + hw + 1, gyh - hh + 1, sh(roof, .6))          # тень карниза на стене
            dw = max(2, hw // 5)
            dx = hx + hw // 2 - dw // 2 - (1 if hw > 8 else 0)
            rect(dx, gyh - max(3, int(hh * .55)), dx + dw, gyh, (80, 54, 40))        # дверь
            ww = 2 if hw < 12 else 3
            wy = gyh - hh + max(1, int(hh * .22))
            for wx in ([hx + 1] if hw < 8 else [hx + 1, hx + hw - ww - 1]):
                rect(wx - 1, wy - 1, wx + ww + 1, wy + ww + 1, (246, 238, 224))      # рама
                rect(wx, wy, wx + ww, wy + ww, (116, 150, 188))
                if ww == 3:
                    rect(wx + 1, wy, wx + 2, wy + ww, (246, 238, 224))
                if rng.random() < .9:
                    bd['lights'].append((wx, wy, hw / 4))
            if big:                                                                  # каменная труба на правом скате
                cxh = hx + int(hw * .72)
                rh = hw - (cxh - hx)
                top_ = gyh - hh - 1 - min(roof_h, max(0, rh // 1)) - 3
                rect(cxh, top_, cxh + 2, gyh - hh - 1 - max(0, roof_h - (cxh - hx) // 1 + (cxh - hx) // 1 * 0) , (128, 108, 100))
                rect(cxh - 1, top_, cxh + 3, top_ + 1, (92, 76, 72))
                bd['smoke'].append((cxh + 1.0, top_, max(1.2, hw / 7)))

        def fence(x0, n, yb):
            for k in range(n):
                xx = x0 + k * 2
                yy = int(near[min(pw - 1, max(0, xx))]) + 2
                rect(xx, yy - 3, xx + 1, yy, (176, 150, 112), .8)
            yy = int(near[min(pw - 1, max(0, x0))]) + 2
            rect(x0, yy - 2, x0 + n * 2, yy - 1, (160, 136, 100), .8)

        if kind != 'windmill':                                                       # лес у подножия / на ближнем холме
            for _ in range(max(4, pw // 7)):
                x = int(rng.integers(0, pw))
                if mount or lake:
                    yb = int(yh) + int(rng.integers(0, 3))
                else:
                    yb = int(near[x]) + 2
                pine(x, yb, max(5, int(ph * (.06 + .05 * rng.random()))), .76)
        if kind == 'village':
            x = spot(.05, .95)
            walls = [(226, 204, 164), (204, 132, 100), (180, 146, 112), (236, 228, 208)]
            roofs = [(158, 74, 58), (104, 76, 68), (78, 98, 128), (120, 62, 52)]
            nh = int(rng.integers(2, 4))
            side = 1 if x < pw / 2 else -1
            for j in range(nh):
                hw = max(10, int(ph * (.14 + .05 * rng.random())))
                hx = int(np.clip(x + side * j * (hw + 4), 2, pw - hw - 3))
                if abs(hx + hw / 2 - tr.cx) < .22 * pw:
                    continue
                gyh = int(near[min(pw - 1, hx + hw // 2)]) + 3
                hh = max(5, int(hw * (.6 + .15 * rng.random())))
                wall, roof = walls[int(rng.integers(4))], ((236, 240, 246) if win else roofs[int(rng.integers(4))])
                if j == nh - 1 and nh > 2 and rng.random() < .6:                     # красный амбар
                    wall, roof = (176, 60, 50), (84, 80, 92)
                house(hx, hw, hh, gyh, wall, roof, big=j != nh - 1 or nh < 3)
            fence(int(np.clip(x - side * 6, 2, pw - 14)), 5, 0)
            if rng.random() < .8:                                                    # фонарь у дороги
                lx = spot(.05, .95)
                ly = int(near[min(pw - 1, lx)]) + 3
                lh = max(5, int(.06 * ph))
                rect(lx, ly - lh, lx + 1, ly + 1, (52, 52, 60), .85)
                rect(lx - 1, ly - lh - 1, lx + 2, ly - lh, (52, 52, 60), .85)
                bd['lights'].append((lx, ly - lh, 4.0))
        elif kind == 'windmill':
            mx = spot(.06, .94)
            my = int(near[min(pw - 1, mx)]) + 2
            mh = max(8, int(.17 * ph))
            for r in range(mh):                                # башня сужается кверху
                w = max(1, int((mh * .36) * (1 - .45 * r / mh)))
                rect(mx - w // 2, my - r - 1, mx - w // 2 + w + 1, my - r, (208, 196, 176) if r % 2 else (192, 178, 156), .85)
            rect(mx - 2, my - mh - 2, mx + 3, my - mh, (120, 84, 70), .85)
            bd['mill'] = (mx + .5, my - mh - 1.0, max(5.0, mh * .85))
        if lake:
            yw = int(yh) + 1
            wm = np.zeros((ph, pw), bool)
            wm[yw:] = True
            bd['water'] = yw
            s.bd_wm = wm
        # непрозрачность там, где закрывает земля: земля сама рисуется в base, поэтому берём только небо над ней
        a_vis = al * (1 - s.gmask[..., 0])
        top = int(max(0, np.argmax(a_vis.max(1) > 0))) if a_vis.max() > 0 else ph
        if lake:
            top = min(top, bd['water'])
        s.bd_hz = (.38 * (1 - dep) ** 1.3).astype(np.float32)
        bd.update(col=col, a=a_vis, dep=dep, top=top, kind=kind, hrow=int(min(yh, gy - 2)))
        s.bd = bd

    def draw_backdrop(s, buf):
        bd = s.bd
        if not bd:
            return
        r0, pw, ph = bd['top'], s.pw, s.ph
        if r0 >= ph:
            return
        hr = bd['hrow']
        sky = buf[:hr + 1, ::max(1, pw // 16)].mean(1)                          # цвет неба по строкам: дальние слои тонут в нём
        sky = np.concatenate([sky, np.repeat(sky[-1:], ph - hr - 1, 0)])[r0:]
        hz = np.clip(s.bd_hz[r0:] + s.fog * .5 * (1 - bd['dep'][r0:]), 0, .95)[..., None]
        c = bd['col'][r0:] * (1 - hz) + sky[:, None, :] * hz
        a = bd['a'][r0:, :, None]
        buf[r0:] = buf[r0:] * (1 - a) + c * a
        yw = bd['water']
        if yw is not None:
            ys = np.arange(yw, ph)
            src = np.clip(2 * yw - 1 - ys, 0, ph - 1)
            xs = np.arange(pw)
            if s.season == 'winter':
                refl = buf[src][:, xs] * .4 + np.array(BD_WATER['winter'], np.float32) * .55
            else:
                sh = np.round(np.sin(ys[:, None] * 1.3 + s.t * 1.6 + xs[None, :] * .09) * (.8 + .6 * s.wnow)).astype(int)
                refl = buf[src[:, None], np.clip(xs[None, :] + sh, 0, pw - 1)] * .58 + np.array(BD_WATER[s.season], np.float32) * .42
                glint = np.clip(np.sin(ys[:, None] * 2.1 - s.t * 2.3 + xs[None, :] * .5) - .93, 0, 1) * 7
                refl = refl + glint[..., None]
            m = (s.bd_wm[yw:] & (s.gmask[yw:, :, 0] < 1))[..., None] * (1 - s.gmask[yw:])
            buf[yw:] = buf[yw:] * (1 - m) + refl * m
        for x, y, z in bd['smoke']:                                              # дым: стоит на ветру столбом из кругов
            for k in range(7):
                age = (s.t * .22 + k / 7) % 1.0
                px = x + age * (3 + 5 * s.wnow) * z + math.sin(age * 6 + k) * .6 * z
                py = y - age * 11 * z
                r = (.8 + 2.2 * age) * z
                a_ = .5 * (1 - age) ** 1.3
                x0, x1, y0, y1 = max(0, int(px - r - 1)), min(pw, int(px + r + 2)), max(0, int(py - r - 1)), min(ph, int(py + r + 2))
                if x1 > x0 and y1 > y0:
                    X, Y = s.gx[:, x0:x1], s.gyy[y0:y1]
                    m = np.clip(r + .5 - np.sqrt((X - px) ** 2 + (Y - py) ** 2), 0, 1)[..., None] * a_
                    buf[y0:y1, x0:x1] = buf[y0:y1, x0:x1] * (1 - m) + np.array((226, 226, 232), np.float32) * m
        if bd['mill']:                                                           # лопасти крутятся быстрее при ветре
            mx, my, ln = bd['mill']
            ang0 = s.t * (.25 + .5 * s.wnow)
            u = np.arange(1, ln, .5)
            for q in range(4):
                a_ = ang0 + q * math.pi / 2
                ix = np.round(mx + np.cos(a_) * u).astype(int)
                iy = np.round(my + np.sin(a_) * u).astype(int)
                ok = (ix >= 0) & (ix < pw) & (iy >= 0) & (iy < ph)
                buf[iy[ok], ix[ok]] = (236, 228, 212)
                for off in (-.5, .5):                                            # лопасть в две линии — потолще
                    ok2 = (ix >= 0) & (ix + 1 < pw) & (iy + 1 < ph) & (iy >= 0)
                    buf[(iy + (1 if abs(math.sin(a_)) < .7 else 0))[ok2], (ix + (1 if abs(math.sin(a_)) >= .7 else 0))[ok2]] = (220, 210, 192)
                    break

    def draw_bd_lights(s, buf):
        """Окна и фонарь светятся ночью и в сумерках: после затемнения кадра."""
        bd = s.bd
        if not bd or not bd['lights']:
            return
        k = float(np.clip((s.lt_night - .2) / .5, 0, 1))
        if k < .02:
            return
        warm = np.array((255, 196, 96), np.float32)
        for x, y, r in bd['lights']:
            r = max(2.0, r)
            x0, x1, y0, y1 = max(0, int(x - r - 1)), min(s.pw, int(x + r + 2)), max(0, int(y - r - 1)), min(s.ph, int(y + r + 2))
            if x1 > x0 and y1 > y0:
                d = np.sqrt((s.gx[:, x0:x1] - x - .5) ** 2 + (s.gyy[y0:y1] - y - .5) ** 2)
                g = np.clip(1 - d / r, 0, 1) ** 2 * .55 * k
                buf[y0:y1, x0:x1] += g[..., None] * warm
            s.put(buf, x, y, warm, min(1.0, k * 1.3))

    # ---------- кадр ----------
    def wind_x(s, x, y, t):
        tr = s.tree
        h = np.clip((tr.gy - y) / tr.th, 0, 1.3)
        amp = s.wnow * .035 * s.ph * h ** 1.7
        w = amp * (np.sin(1.3 * t + x * .05) + .45 * np.sin(2.9 * t + x * .11 + 1.7)) * (.7 + .3 * math.sin(.23 * t))
        R2 = max(8, s.ph * .13) ** 2
        for gx, gy, gv, g0 in s.gusts:  # порывы от мыши: качнуло и затухло
            age = t - g0
            if age < 2.6:
                w = w + gv * np.exp(-((x - gx) ** 2 + (y - gy) ** 2) / R2) * np.exp(-age * 1.5) * math.sin(age * 9)
        return w

    def gust(s, x, y, v):
        s.gusts.append((x, y, v, s.t))
        del s.gusts[:-14]

    def add_particles(s, nx, ny, nc, vy, vx=None, vt=None, ph=None):
        n = len(nx)
        s.fvt = np.concatenate([s.fvt, np.asarray(vy if vt is None else vt, np.float32) * np.ones(n, np.float32)])
        vx = np.zeros(n) if vx is None else vx
        s.fx = np.concatenate([s.fx, np.asarray(nx, np.float32)])
        s.fy = np.concatenate([s.fy, np.asarray(ny, np.float32)])
        s.fvy = np.concatenate([s.fvy, np.asarray(vy, np.float32)])
        s.fvx = np.concatenate([s.fvx, np.asarray(vx, np.float32)])
        s.fph = np.concatenate([s.fph, (np.random.uniform(0, 6.28, n) if ph is None else np.asarray(ph)).astype(np.float32)])
        s.fc = np.concatenate([s.fc, np.asarray(nc, np.float32).reshape(n, 3)])
        s.fz = np.concatenate([s.fz, np.random.uniform(0, 1, n).astype(np.float32)])   # <.5 — за стволом, иначе перед ним

    def mouse_move(s, x, y):
        """Мышь без кнопки: толкает дерево, упавшие куски и листья."""
        if s.mouse is not None:
            dx, dy = x - s.mouse[0], y - s.mouse[1]
            if abs(dx) >= .8 or abs(dy) >= 1.5:
                v = dx * .9 if abs(dx) >= .8 else math.copysign(abs(dy) * .45, s.mdir)
                s.mdir = 1 if v >= 0 else -1
                s.gust(x, y, max(-5.0, min(5.0, v)))
                s.scare(x, y, max(14, s.ph * .16))
                s.push(x, y, dx if abs(dx) >= .8 else math.copysign(abs(dy) * .5, s.mdir))
        s.mouse = (x, y)

    def push(s, x, y, dx):
        R = max(9, s.ph * .12)
        for p in s.pieces:
            if not p.log and not p.fell and math.hypot(p.cx - x, p.cy - y) < R + p.rad * .6:
                p.rest, p.age, p.alpha = False, 0.0, 1.0
                p.vx += max(-30, min(30, dx * 3))
                p.vy -= min(14, abs(dx) * 1.5)
                p.w += dx * .1
        if len(s.fx):
            near = (s.fx - x) ** 2 + (s.fy - y) ** 2 < R * R
            s.fvx[near] += max(-30, min(30, dx * 3))

    def press(s, x, y):
        if s.lighter:
            s.mouse, s.lit = (x, y), True
            s.ignite_near(x, y - 2, 4.0)
            return
        s.drag = [(x, y)]
        s.mouse = None

    def drag_to(s, x, y):
        if s.lighter:
            s.mouse, s.lit = (x, y), True
            return
        if s.drag is None:
            s.drag = [(x, y)]
        elif math.hypot(x - s.drag[-1][0], y - s.drag[-1][1]) >= .6:
            s.drag.append((x, y))

    def release(s, x, y):
        if s.lighter:
            was, s.lit = s.lit, False
            if was:                        # поджигаем, только если нажатие началось на сцене (клик по кнопке панели не считается)
                s.mouse = (x, y)
                s.ignite_near(x, y - 2, 4.0)
            return
        if s.drag is None:
            return
        s.drag.append((x, y))
        path, s.drag = s.drag, None
        s.mouse = (x, y)
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))
        if length >= 2.5:
            s.slash.append((path, s.t))
            s.cut(path, 'cut')
        else:
            s.click(x, y)

    def click(s, x, y):
        """Клик без протяжки: топор/семя по инструменту, плод с земли в корзину, иначе спугнуть зверя и сбить плод."""
        if s.gone and s.tl is None:
            s.plant_new()
            return
        if s.tool_click(x, y):
            return
        s.scare(x, y, 5 * s.zs())
        if s.season in ('summer', 'autumn') and len(s.fr_i):
            tr, i = s.tree, s.fr_i
            ripe = s.fruit_ripe()
            px = tr.lx[i] + s.wind_x(tr.lx[i], tr.ly[i], s.t)
            vis = (ripe > 0) & (s.progress() >= tr.lb[i]) & ~s.lcut[i] & ~s.sev[tr.lseg[i]]
            s.drop_fruit(np.where(vis & (np.hypot(px - x, tr.ly[i] - y) < 3.5))[0], ripe)

    def shake(s, x, y):
        """Клик без протяжки: встряхнуть крону, сорвать часть листьев (зимой — снег)."""
        tr = s.tree
        s.gust(x, y, s.mdir * 5.0)
        R = max(10, s.ph * .17)
        rng = np.random.default_rng()
        if s.cols is not None:
            d2 = (tr.lx - x) ** 2 + (tr.ly - y) ** 2
            idx = np.where((s.progress() >= tr.lb) & (d2 < R * R) & ~s.lcut & ~s.sev[tr.lseg])[0]
            if len(idx) == 0:
                return
            k = rng.choice(idx, min(len(idx), 32), replace=False)
            s.drop_leaves(k, tr.lx[k] + s.wind_x(tr.lx[k], tr.ly[k], s.t), tr.ly[k])
        else:
            n = 28
            s.add_particles(x + rng.normal(0, R * .5, n), y + rng.normal(0, R * .3, n),
                            np.tile(np.array(SEASONS[s.season]['fcol'], np.float32), (n, 1)), rng.uniform(3, 8, n))

    def drop_leaves(s, k, x, y, vx0=0.0):
        """Листья k падают кучками: соседи (клетка 4 px) делят скорость, снос и фазу качания."""
        if len(k) == 0:
            return
        s.lcut[k] = True
        s.lcutt[k] = s.gt
        if s.cols is None:
            return
        _, cl = np.unique(np.floor(x / 4).astype(int) * 100003 + np.floor(y / 4).astype(int), return_inverse=True)
        m, n = cl.max() + 1, len(k)
        vt, vx, ph, vy = (np.random.uniform(*r, m) for r in ((17, 34), (-6, 6), (0, 6.28), (3, 12)))
        jit = np.random.uniform(.94, 1.06, n)
        s.add_particles(x, y, s.cols[k] * 1.1, vy[cl] * jit, vx[cl] + vx0, vt=vt[cl] * jit, ph=ph[cl] + np.random.normal(0, .15, n))

    def anchored(s, idx, near):
        """Связная масса листвы (клетки 2.5 px) должна касаться коры, иначе она остров в воздухе."""
        tr = s.tree
        cx, cy = np.floor(tr.lx[idx] / 2.5).astype(int), np.floor(tr.ly[idx] / 2.5).astype(int)
        key = cx * 4096 + cy
        cells, inv = np.unique(key, return_inverse=True)
        ok = np.zeros(len(cells), bool)
        ok[inv[near]] = True
        pos = {int(k): i for i, k in enumerate(cells)}
        seen = np.zeros(len(cells), bool)
        for i0 in range(len(cells)):
            if seen[i0]:
                continue
            comp, st, hold = [i0], [i0], bool(ok[i0])
            seen[i0] = True
            while st:
                k = int(cells[st.pop()])
                for dx in (-4096, 0, 4096):
                    for dy in (-1, 0, 1):
                        j = pos.get(k + dx + dy)
                        if j is not None and not seen[j]:
                            seen[j] = True
                            comp.append(j)
                            st.append(j)
                            hold |= bool(ok[j])
            if hold:
                ok[comp] = True
        return ok[inv]

    def support_dist(s, lk, sev):
        """Расстояние от листьев lk до ближайшей живой (не срезанной) коры."""
        tr = s.tree
        S = tr.S
        ok = ~sev & (tr.par != -2)
        u = np.array([0, .5, 1], np.float32)[None, :]
        px = (S[ok, 0, None] + (S[ok, 2] - S[ok, 0])[:, None] * u).ravel()
        py = (S[ok, 1, None] + (S[ok, 3] - S[ok, 1])[:, None] * u).ravel()
        out = np.full(len(lk), 1e9, np.float32)
        if len(px) == 0:
            return out
        for c in range(0, len(lk), 400):
            q = lk[c:c + 400]
            out[c:c + 400] = np.sqrt(((tr.lx[q, None] - px[None]) ** 2 + (tr.ly[q, None] - py[None]) ** 2).min(1))
        return out

    def cut(s, path, mode='cut', fall=1, only=None):
        """Срез по линии: задетые отрезки падают вместе со всем, что на них растёт.
        mode: cut — отрастает от пня; prune — форма: не отрастает никогда; fell — валка ствола: целиком, лежит бревном, пень отрастёт позже."""
        tr, G = s.tree, s.progress()
        P = np.array(path, np.float32)
        pts = [P[0]]
        for a, b in zip(P[:-1], P[1:]):
            for k in range(1, max(1, int(np.hypot(*(b - a)) / .5)) + 1):
                pts.append(a + (b - a) * k / max(1, int(np.hypot(*(b - a)) / .5)))
        pts = np.array(pts, np.float32)
        g = s.geom(G)
        x0, y0, x1, y1, r0, r1, f = g
        dx, dy = x1 - x0, y1 - y0
        px, py = pts[:, 0:1], pts[:, 1:2]
        t = np.clip(((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy + 1e-9), 0, 1)
        d = np.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
        hit = (d <= r0 + (r1 - r0) * t + .9).any(0) & (f > 0) & (tr.par != -2)
        if only is not None:
            hit = np.zeros_like(hit)
            hit[only] = f[only] > 0
        new = tr.descend(hit)  # и всё, что на них растёт (в т.ч. ещё не отросшее — отрастание начнётся заново)
        # кусок = задетый отрезок и его потомки; pid — номер куска у каждого отрезка
        pid, par = np.full(len(hit), -1), tr.parl
        for j in np.where(new)[0]:
            pid[j] = j if (hit[j] and not (par[j] >= 0 and new[par[j]])) else pid[par[j]]
        lvis = (G >= tr.lb) & ~s.lcut & ~s.sev[tr.lseg]
        lx = tr.lx + s.wind_x(tr.lx, tr.ly, s.t)
        ly = tr.ly
        carried = np.zeros(len(lx), bool)
        if mode == 'fell':
            roots = np.unique(pid[new])
            root = roots[np.argmin(y0[roots])] if len(roots) else None
            segs = np.where(new & (f > 0))[0]
            if root is not None and len(segs):
                carried = lvis & new[tr.lseg] if s.cols is not None else carried
                lk = np.where(carried)[0]
                pv = (float(x0[root]), float(y0[root]))
                pc = Piece(s, segs, g, lk, lx, ly, pv)
                pc.start_fall(pv, fall)
                s.pieces.append(pc)
                s.stump = dict(x=pv[0], y=pv[1], r=float(r0[root]), root=int(root), t=s.t, years=1 + int(min(s.gt, MATURE * 1.5) / 90))
            roots = []
        else:
            roots = np.unique(pid[new])
        for root in roots:
            segs = np.where(pid == root)[0]
            segs = segs[f[segs] > 0]
            if len(segs):  # большой кусок крошится на обломки по клеткам 12 px, чтобы не падал целым «деревом»
                mx, my = (x0[segs] + x1[segs]) / 2, (y0[segs] + y1[segs]) / 2
                cell = np.floor(mx / (.07 * s.ph)).astype(int) * 1009 + np.floor(my / (.07 * s.ph)).astype(int) if np.ptp(mx) + np.ptp(my) > .09 * s.ph else np.zeros(len(segs), int)
                for c in np.unique(cell):
                    s.pieces.append(Piece(s, segs[cell == c], g, np.zeros(0, int), lx, ly, (x0[root], y0[root])))
        if True:
            drop = lvis & new[tr.lseg] & ~carried  # листва срезанных веток (при валке она едет на упавшем стволе)
            direct = np.zeros(len(lx), bool)
            for c in range(0, len(pts), 64):  # листья под линией
                q = pts[c:c + 64]
                direct |= (((lx[:, None] - q[None, :, 0]) ** 2 + (ly[:, None] - q[None, :, 1]) ** 2) < 9).any(1)
            drop |= direct & lvis
            # листья, у которых рядом не осталось коры, не висят в воздухе
            rest = np.where(lvis & ~drop)[0]
            if len(rest) and new.any():  # опора пропадает только если что-то срезано
                dist = s.support_dist(rest, s.sev | new)
                lost = dist > tr.sup0[rest] + .035 * s.ph
                lost |= ~s.anchored(rest, dist < 2.5)
                drop[rest[lost]] = True
            k = np.where(drop)[0]
            s.drop_leaves(k, lx[k], ly[k], (P[-1, 0] - P[0, 0]) * .08)
        s.trim_pieces()
        s.scare(float(P[:, 0].mean()), float(P[:, 1].mean()), s.ph * .4)
        keep = new & ~s.perm                      # то, что уже срезано навсегда, снова не отрастает
        s.sevt[keep] = s.gt + (s.fell_delay if mode == 'fell' else 0.0)
        if mode == 'prune':
            s.perm |= new
            s.sevt[new] = 1e9
        s.sevb[new] = tr.S[pid[new], 6]
        s.lcut[new[tr.lseg]] = True
        s.lcutt[new[tr.lseg]] = s.gt
        s.cutv += 1
        s.update_rf()

    def progress(s):
        return min(1.0, s.gt / s.grow_time) * s.tree.maxb * 1.25  # с запасом: листья распускаются после коры

    def grown(s):
        return s.gt > s.grow_time * 1.12

    def mature(s):
        """0..1: возраст после первого роста; толще ветки, гуще крона."""
        return float(smoothstep((s.gt - s.grow_time * 1.12) / MATURE))

    def update_rf(s):
        """Отрастание срезанного: фронт идёт от пня вдоль ветки (после паузы 3 с)."""
        S = s.tree.S
        R = s.rrate * (s.gt - s.sevt - 3.0) + s.sevb
        s.rf = np.clip((R - S[:, 6]) / np.maximum(S[:, 7] - S[:, 6], 1e-3), 0, 1).astype(np.float32)
        s.sev = s.rf < 1

    def regrow_leaves(s):
        tr = s.tree
        cand = np.where(s.lcut & ~s.lperm & (s.rf[tr.lseg] >= 1) & (s.gt >= s.lcutt + s.ldel))[0]
        if not len(cand):
            return
        if len(cand) > 150:
            cand = np.random.default_rng().choice(cand, 150, replace=False)
        ok = s.support_dist(cand, s.sev) <= tr.sup0[cand] + .035 * s.ph
        s.lcut[cand[ok]] = False
        s.lborn[cand[ok]] = s.gt
        bad = cand[~ok]
        s.lcutt[bad] = s.gt - s.ldel[bad] + 3  # опоры ещё нет — проверим позже

    def geom(s, G):
        """Отрезки дерева в кадре: рост, ветер и порывы уже учтены (по всем, без фильтра)."""
        key = (s.t, s.gt, s.cutv)
        if s.gmemo and s.gmemo[0] == key:
            return s.gmemo[1]
        S = s.tree.S
        f = np.minimum(np.clip((G - S[:, 6]) / np.maximum(S[:, 7] - S[:, 6], 1e-3), 0, 1), s.rf)
        x0, y0 = S[:, 0], S[:, 1]
        x1, y1 = x0 + (S[:, 2] - x0) * f, y0 + (S[:, 3] - y0) * f
        th = 1 + .6 * s.mature() * s.tree.thk
        r0, r1 = S[:, 4] * th, (S[:, 4] + (S[:, 5] - S[:, 4]) * f) * th
        g = x0 + s.wind_x(x0, y0, s.t), y0, x1 + s.wind_x(x1, y1, s.t), y1, r0, r1, f
        s.gmemo = (key, g)
        return g

    # ---------- таймлапс ----------
    def start_timelapse(s):
        """Новое дерево-росток: за TL_DUR секунд — три года по четыре сезона, ствол растёт и толстеет; день, ясно."""
        s.tl_saved = (s.tod_name, s.spd, s.rmode, s.wx_name)
        s.tod_name, s.spd, s.rmode, s.wx_name = 'day', 3, False, 'clear'
        s.season, s.seed = 'spring', random.randrange(10 ** 6)
        s.new_tree()
        s.gt, s.tl = 0.0, 0.0

    def end_timelapse(s):
        if s.tl_saved:
            s.tod_name, s.spd, s.rmode, s.wx_name = s.tl_saved
        s.tl = s.tl_saved = None

    def step_timelapse(s, dt):
        s.tl += dt
        u = s.tl / TL_DUR
        if u >= 1:
            s.end_timelapse()
            return
        g1 = s.grow_time * 1.12                                     # первый год — рост до полной высоты, дальше толстеет
        s.gt = g1 * min(1.0, u * 3) + MATURE * max(0.0, u - 1 / 3) * 1.5
        sn = SEASON_NAMES[int(u * 12) % 4]
        if sn != s.season:
            s.season = sn
            s.restyle()

    # ---------- погода, свет, живность ----------
    def hour(s):
        """Час суток: в бесконечном режиме идёт сам (CLOCK_RATE), иначе по МСК."""
        if s.clock is not None:
            return s.clock
        h = datetime.datetime.now(ZoneInfo('Europe/Moscow'))
        return h.hour + h.minute / 60

    def tod_target(s):
        if s.tod_name != 'auto':
            return LIGHT[s.tod_name]
        h = s.hour()
        for (h0, (c0, n0)), (h1, (c1, n1)) in zip(DAY_KEYS, DAY_KEYS[1:]):
            if h0 <= h <= h1:
                u = (h - h0) / (h1 - h0)
                return tuple(a + (b - a) * u for a, b in zip(c0, c1)), n0 + (n1 - n0) * u
        return L_DAY

    def snap_env(s):
        """Без плавного перехода: сразу целевые погода и свет (для скриншотов и переноса при ресайзе)."""
        s.rain, s.fog, s.storm = WEATHER[s.wx_name]
        s.wet = float(s.rain)
        c, n = s.tod_target()
        s.lt_tint, s.lt_night = np.array(c, np.float32), float(n)

    def update_env(s, dt):
        k = 1 - math.exp(-dt * .7)
        tr, tf, ts = WEATHER[s.wx_name]
        s.rain += (tr - s.rain) * k
        s.fog += (tf - s.fog) * k
        s.storm += (ts - s.storm) * k
        s.wet += (s.rain - s.wet) * (1 - math.exp(-dt * .12))
        s.wnow = s.wind + 1.8 * s.storm + .4 * s.rain
        c, n = s.tod_target()
        k2 = 1 - math.exp(-dt * 1.5)
        s.lt_tint = s.lt_tint + (np.array(c, np.float32) - s.lt_tint) * k2
        s.lt_night += (n - s.lt_night) * k2
        s.update_rain(dt)
        s.update_flash(dt)

    def update_rain(s, dt):
        eff = min(1.4, s.rain + .5 * s.storm)
        n = np.random.poisson(eff * s.pw * 1.5 * dt) if eff > .02 else 0
        if n:
            s.rx = np.concatenate([s.rx, np.random.uniform(-8, s.pw + 8, n).astype(np.float32)])
            s.ry = np.concatenate([s.ry, np.random.uniform(-8, -1, n).astype(np.float32)])
            s.rv = np.concatenate([s.rv, (np.random.uniform(95, 130, n) * (1 + .3 * s.storm)).astype(np.float32)])
        if len(s.rx):
            s.ry += s.rv * dt
            s.rx += (4 * s.wnow + 10 * s.storm) * dt
            hit = s.ry >= s.tree.gnd(s.rx) - .5
            for x, y in zip(s.rx[hit][:40], s.ry[hit][:40]):
                s.splash.append((float(x), float(y), s.t))
            keep = ~hit & (s.rx < s.pw + 10)
            s.rx, s.ry, s.rv = s.rx[keep], s.ry[keep], s.rv[keep]
        s.splash = [q for q in s.splash if s.t - q[2] < .22][-300:]

    def update_flash(s, dt):
        s.flash *= math.exp(-dt * 9)
        if s.bolt and s.t - s.bolt[0] > .2:
            s.bolt = None
        if s.storm < .5:
            return
        s.next_flash -= dt
        if s.next_flash <= 0:
            s.flash = 1.0
            s.next_flash = random.uniform(6, 14)
            s.double = s.t + random.uniform(.1, .2)
            if random.random() < .2 and s.strike() is not None:   # в дерево — реже: ветка ломается в среднем раз в ~минуты
                return
            x = random.uniform(.15, .85) * s.pw
            pts, y = [(x, 0.0)], 0.0
            while y < s.tree.gnd(x):
                y += random.uniform(3, 6)
                x += random.uniform(-3.5, 3.5)
                pts.append((x, y))
            s.bolt = (s.t, pts)
        elif getattr(s, 'double', 0) and s.t >= s.double:
            s.flash, s.double = .8, 0

    def calm(s):
        return s.rain < .5 and s.storm < .1 and s.lt_night < .6

    def pick_spot(s, g):
        x0, y0, x1, y1, r0, r1, f = g
        tr = s.tree
        dx, dy = np.abs(x1 - x0), np.abs(y1 - y0)
        ok = (f >= 1) & (s.rf >= 1) & (tr.par != -2) & (dx + dy > .7) & (dy <= dx * 1.1 + .1) \
            & (y0 < tr.gnd(x0) - 10) & (y0 > .15 * s.ph)
        for b in s.birds:
            ok &= np.hypot(x0 - b.x, y0 - b.y) > 8
        thick = np.where(ok & (r0 >= .4))[0]  # лучше на ветках потолще, иначе на любых
        idx = thick if len(thick) else np.where(ok)[0]
        if not len(idx):
            return None
        return int(random.choice(idx)), random.uniform(.3, .8)

    def anchor(s, g, seg, u):
        x0, y0, x1, y1, r0, r1, f = g
        return x0[seg] + (x1[seg] - x0[seg]) * u, y0[seg] + (y1[seg] - y0[seg]) * u - (r0[seg] + (r1[seg] - r0[seg]) * u) - .6

    def update_fauna(s, dt):
        g = s.geom(s.progress())
        calm = s.calm()
        f = g[6]
        s.bird_timer -= dt
        if calm and s.grown() and len(s.birds) < 3 and s.bird_timer <= 0:
            s.bird_timer = random.uniform(6, 20)
            spot = s.pick_spot(g)
            if spot:
                side = random.choice((-1, 1))
                b = Bird(-4.0 if side < 0 else s.pw + 4.0, random.uniform(.12, .4) * s.ph, *spot)
                s.birds.append(b)
        for b in s.birds:
            if b.state != 'out' and (not calm or f[b.seg] < 1 or s.rf[b.seg] < 1):
                b.leave(s.pw)
            if b.state == 'out':
                b.x += b.vx * dt
                b.y += b.vy * dt
                b.vy -= 4 * dt
                continue
            ax, ay = s.anchor(g, b.seg, b.u)
            if b.state == 'in':
                d = math.hypot(ax - b.x, ay - b.y)
                sp = 30 * min(1.0, d / 14 + .25) * dt
                if d < max(.8, sp):
                    b.x, b.y, b.state = ax, ay, 'perch'
                else:
                    b.x += (ax - b.x) / d * sp
                    b.y += (ay - b.y) / d * sp + math.sin(s.t * 5 + id(b) % 7) * .08
                    b.face = 1 if ax > b.x else -1
            else:
                b.x, b.y = ax, ay
                b.wait -= dt
                b.look -= dt
                if b.look <= 0:
                    b.look = random.uniform(2, 5)
                    if random.random() < .5:
                        b.face = -b.face
                    else:
                        b.u = min(.9, max(.15, b.u + random.uniform(-.12, .12)))
                if b.wait <= 0:
                    b.leave(s.pw)
        s.birds = [b for b in s.birds if -8 < b.x < s.pw + 8 and b.y > -10]
        # бабочки: тёплое время, день, ясно
        want = 3 if s.season == 'summer' else 2 if s.season == 'spring' else 0
        day = calm and s.lt_night < .2 and s.grown() and want
        s.bf_timer -= dt
        if day and len(s.bflies) < want and s.bf_timer <= 0:
            s.bf_timer = random.uniform(3, 9)
            side = random.choice((-1, 1))
            s.bflies.append(dict(x=-3.0 if side < 0 else s.pw + 3.0, y=random.uniform(.45, .78) * s.ph,
                                 th=0.0 if side < 0 else math.pi, col=random.choice(BFLY), ph=random.uniform(0, 6.28), gone=False))
        for q in s.bflies:
            q['gone'] = q['gone'] or not day
            if q['gone']:
                q['y'] -= 10 * dt
                q['th'] = -1.4
            else:
                q['th'] += random.gauss(0, 2.2) * dt
                if q['x'] < 5 and math.cos(q['th']) < 0 or q['x'] > s.pw - 5 and math.cos(q['th']) > 0:
                    q['th'] = math.pi - q['th']
                if q['y'] < .3 * s.ph and math.sin(q['th']) < 0 or q['y'] > .8 * s.ph and math.sin(q['th']) > 0:
                    q['th'] = -q['th']
            q['x'] += math.cos(q['th']) * 9 * dt
            q['y'] += math.sin(q['th']) * 9 * dt
        s.bflies = [q for q in s.bflies if -6 < q['x'] < s.pw + 6 and q['y'] > -3]

    # ---------- живое окружение: плоды, лужи, радуга, трава, звери ----------
    def put(s, buf, x, y, c, a=1.0, sz=1):
        ix, iy = int(round(x)), int(round(y))
        for dy in range(sz):
            for dx in range(sz):
                if 0 <= ix + dx < s.pw and 0 <= iy + dy < s.ph:
                    buf[iy + dy, ix + dx] = buf[iy + dy, ix + dx] * (1 - a) + np.asarray(c, np.float32) * a

    def fruit_ripe(s):
        if not s.grown() or not len(s.fr_off):
            return np.zeros(len(s.fr_off))
        return np.clip((s.gt - s.grow_time * 1.12 - s.fr_off) / 60, 0, 1)

    def fruit_color(s, k):
        ripe, raw = FRUIT[s.preset][0], FRUIT[s.preset][1]
        return np.array(raw, np.float32) + (np.array(ripe, np.float32) - np.array(raw, np.float32)) * k

    def update_extras(s, dt):
        tr, pw = s.tree, s.pw
        if s.rmode:
            s.clock = ((s.hour() if s.clock is None else s.clock) + dt * CLOCK_RATE) % 24
        else:
            s.clock = None
        quiet = s.rain < .4 and s.storm < .1
        # радуга: дождь кончился, день
        if s.rain > .6:
            s.was_rain = True
        if s.was_rain and s.rain < .12 and s.storm < .1:
            s.was_rain = False
            if s.lt_night < .3 and random.random() < .8:
                s.rb = (s.t, random.uniform(.35, .65) * pw)
        if s.rb and (s.t - s.rb[0] > 40 or s.rain > .5 or s.lt_night > .45):  # радуга живёт 40 с и гаснет с наступлением вечера
            s.rb = None
        # падающие звёзды; изредка метеоритный дождь, северное сияние
        night = s.lt_night > .8 and s.rain < .3 and s.fog < .5
        s.met_t -= dt
        if s.shower and (s.t - s.shower > 22 or not night):
            s.shower = None
        if s.met_t <= 0:
            s.met_t = random.uniform(.3, .9) if s.shower else random.uniform(14, 40)
            if night:
                if not s.shower and random.random() < .06:
                    s.shower = s.t
                sg = random.choice((-1, 1))
                v = pw * random.uniform(.7, 1.0)
                s.meteors.append(dict(t0=s.t, x=(random.uniform(.1, .5) if sg > 0 else random.uniform(.5, .9)) * pw,
                                      y=random.uniform(.04, .28) * s.ph, vx=sg * v, vy=v * .38))
        s.meteors = [m for m in s.meteors if s.t - m['t0'] <= 1.0][-12:]
        s.aur_t -= dt
        if s.aurora and (s.t - s.aurora[0] > s.aurora[1] or s.lt_night < .5):
            s.aurora = None
        if s.aur_t <= 0:
            s.aur_t = random.uniform(60, 150)
            if night and not s.aurora and random.random() < .4:
                s.aurora = (s.t, random.uniform(45, 80))
        # снег копится зимой, лужи — от дождя
        if s.season == 'winter':
            if s.grown():
                s.snowd = min(1.0, s.snowd + dt / 150)
            s.pud = 0.0
        else:
            s.snowd = 0.0
            s.pud = min(1.0, s.pud + dt / 15) if s.rain > .3 else max(0.0, s.pud - dt / 90)
        s.update_drift(dt)
        s.update_fruit(dt)
        s.update_critters(dt, quiet)
        s.update_ground_critters(dt, quiet)

    def update_drift(s, dt):
        """Сильный ветер несёт по небу листья, лепестки или снег."""
        cfg = SEASONS[s.season]
        n = np.random.poisson(max(0.0, s.wnow - .6) * 1.2 * s.pw / 80 * dt) if s.grown() and len(s.drift) < 40 else 0
        for _ in range(n):
            if cfg['pal']:
                c = np.array(random.choices([c for c, _ in cfg['pal']], [w for _, w in cfg['pal']])[0], np.float32) * 1.1
            else:
                c = np.array(cfg['fcol'], np.float32)
            s.drift.append([-2.0, random.uniform(.08, .62) * s.ph, random.uniform(0, 6.28), c])
        keep = []
        for q in s.drift:
            q[0] += (10 + 9 * s.wnow) * dt
            q[1] += (math.sin(s.t * 2.3 + q[2]) * 4 + 1.2) * dt
            if q[0] < s.pw + 3 and q[1] < float(s.tree.gnd(min(max(q[0], 0), s.pw - 1))):
                keep.append(q)
        s.drift = keep

    def update_fruit(s, dt):
        tr = s.tree
        gnd = float
        if s.season in ('summer', 'autumn') and len(s.fr_i) and not s.gone:   # сгоревшее дерево плодов не роняет
            ripe = s.fruit_ripe()
            i = s.fr_i
            vis = (ripe > 0) & (s.progress() >= tr.lb[i])
            go = vis & (s.lcut[i] | s.sev[tr.lseg[i]])
            if s.season == 'autumn':
                go |= vis & (ripe >= 1) & (np.random.random(len(i)) < dt * .006)
            s.drop_fruit(np.where(go)[0], ripe)
        keep = []
        for q in s.fr_fall:
            q[2] += 70 * dt
            q[1] += q[2] * dt
            q[0] += 1.2 * s.wnow * dt
            if q[1] >= float(tr.gnd(q[0])) - 1:
                s.fr_gnd.append((q[0], q[3], s.t))
            else:
                keep.append(q)
        s.fr_fall = keep
        s.fr_gnd = [q for q in s.fr_gnd if s.t - q[2] < 150][-16:]

    def drop_fruit(s, js, ripe):
        tr = s.tree
        for j in js:
            i = s.fr_i[j]
            k = ripe[j] * (1.0 if s.season == 'autumn' else .55)
            s.fr_fall.append([float(tr.lx[i] + s.wind_x(tr.lx[i], tr.ly[i], s.t)), float(tr.ly[i]), 0.0, s.fruit_color(k)])
            s.fr_off[j] = s.gt - s.grow_time * 1.12 + 90   # на ветке новый нальётся через полторы минуты

    def update_critters(s, dt, quiet):
        tr, pw = s.tree, s.pw
        g = s.geom(s.progress())
        f = g[6]
        # сова: ночью на ветке
        o = s.owl
        s.owl_t -= dt
        if o is None and s.owl_t <= 0:
            s.owl_t = random.uniform(10, 30)
            if quiet and s.lt_night > .75 and s.grown():
                spot = s.pick_spot(g)
                if spot:
                    s.owl = o = dict(seg=spot[0], u=spot[1], state='sit', x=0.0, y=0.0, vx=0.0, vy=0.0, blink=random.uniform(2, 5),
                                     face=random.choice((-1, 1)), t0=s.t)
        if o:
            if o['state'] == 'sit':
                o['x'], o['y'] = s.anchor(g, o['seg'], o['u'])
                if s.lt_night < .45 or f[o['seg']] < 1 or s.rf[o['seg']] < 1 or not quiet:
                    o['state'], o['vx'], o['vy'] = 'out', o['face'] * 18, -9
                o['blink'] -= dt
                if o['blink'] < -.16:
                    o['blink'] = random.uniform(2.5, 6)
            else:
                o['x'] += o['vx'] * dt
                o['y'] += o['vy'] * dt
                o['vy'] -= 3 * dt
                if not -8 < o['x'] < pw + 8 or o['y'] < -10:
                    s.owl = None
        # белка: днём по земле, на ствол, посидела, вниз, ушла
        q = s.squirrel
        s.sq_t -= dt
        day = s.lt_night < .3 and quiet and s.grown() and s.mature() > .05 and s.ph >= 40
        if q is None and s.sq_t <= 0:
            s.sq_t = random.uniform(30, 80)
            if day:
                side = random.choice((-1, 1))
                s.squirrel = q = dict(side=side, x=-3.0 if side < 0 else pw + 3.0, y=0.0, state='in', wait=0.0,
                                      top=random.uniform(.10, .26) * tr.th)
        if q:
            r = max(1.8, float(tr.S[:, 4].max()) * (1 + .6 * s.mature())) + .8
            tx = tr.cx + q['side'] * r
            gy0 = float(tr.gnd(tx)) - 1
            if not day and q['state'] in ('in', 'climb', 'sit'):
                q['state'] = 'down' if q['state'] != 'in' else 'out'
            st = q['state']
            if st == 'in':
                q['x'] -= q['side'] * 14 * dt
                q['y'] = float(tr.gnd(q['x'])) - 1
                if (q['x'] - tx) * -q['side'] >= 0:
                    q['x'], q['state'] = tx, 'climb'
            elif st == 'climb':
                q['y'] = min(q['y'] or gy0, gy0) - 9 * dt
                if q['y'] <= gy0 - q['top']:
                    q['state'], q['wait'] = 'sit', random.uniform(4, 9)
            elif st == 'sit':
                q['wait'] -= dt
                if q['wait'] <= 0:
                    q['state'] = 'down'
            elif st == 'down':
                q['y'] += 10 * dt
                if q['y'] >= gy0:
                    q['y'], q['state'] = gy0, 'out'
            else:
                q['x'] += q['side'] * 18 * dt
                q['y'] = float(tr.gnd(q['x'])) - 1
                if not -6 < q['x'] < pw + 6:
                    s.squirrel = None
        # олень: редкий гость, проходит по земле и иногда щиплет траву
        d = s.deer
        s.deer_t -= dt
        if d is None and s.deer_t <= 0:
            s.deer_t = random.uniform(120, 300)
            if quiet and s.lt_night < .75 and s.grown() and s.ph >= 56:
                dr = random.choice((-1, 1))
                z = s.zs()
                s.deer = d = dict(x=-12.0 * z if dr > 0 else pw + 12.0 * z, dir=dr, z=z, state='walk', wait=random.uniform(6, 14), flee=False)
        if d:
            if d['state'] == 'walk':
                d['x'] += d['dir'] * (22 if d['flee'] else 5) * dt
                d['wait'] -= dt
                if d['wait'] <= 0 and .15 * pw < d['x'] < .85 * pw and not d['flee']:
                    d['state'], d['wait'] = 'graze', random.uniform(4, 7)
            else:
                d['wait'] -= dt
                if d['wait'] <= 0:
                    d['state'], d['wait'] = 'walk', random.uniform(8, 16)
            if not -14 * d['z'] < d['x'] < pw + 14 * d['z']:
                s.deer = None

    def zs(s):
        """Во сколько раз рисовать зверей крупнее: на большой панели иначе теряются."""
        return 1 if s.ph < 100 else 2 if s.ph < 180 else 3

    def update_ground_critters(s, dt, quiet):
        pw, z = s.pw, s.zs()
        for kind, cfg in GCRIT.items():
            c = s.gc.get(kind)
            s.gc_t[kind] = s.gc_t.get(kind, random.uniform(*cfg['t'])) - dt
            if c is None and s.gc_t[kind] <= 0:
                s.gc_t[kind] = random.uniform(*cfg['t'])
                ok = quiet and s.grown() and s.ph >= 40 and s.season != 'winter'
                ok = ok and (s.lt_night > .25 if kind == 'hedgehog' else s.lt_night > .3 if kind == 'fox' else s.pud > .3 and s.rain < .3)
                if kind == 'fox':
                    ok = quiet and s.grown() and s.ph >= 40 and s.lt_night > .3
                if ok:
                    dr = random.choice((-1, 1))
                    s.gc[kind] = c = dict(x=-7.0 * z if dr > 0 else pw + 7.0 * z, dir=dr, state='walk', wait=random.uniform(5, 12),
                                          yo=random.uniform(.025, .065), t0=s.t, flee=False)
            if c:
                st = c['state']
                if st == 'walk':
                    c['x'] += c['dir'] * cfg['v'] * (2.4 if c['flee'] else 1) * dt
                    c['wait'] -= dt
                    if c['wait'] <= 0 and kind != 'snail' and not c['flee'] and .15 * pw < c['x'] < .85 * pw:
                        c['state'], c['wait'] = 'stop', random.uniform(2, 4)
                else:
                    c['wait'] -= dt
                    if c['wait'] <= 0:
                        c['state'], c['wait'] = 'walk', random.uniform(6, 14)
                if not -9 * z < c['x'] < pw + 9 * z or (kind == 'snail' and s.t - c['t0'] > 150):
                    del s.gc[kind]
        # гнездо: на ветке весной и летом, птенцы подрастают; упадёт, если ветку срезали
        g = s.geom(s.progress())
        s.nest_t -= dt
        if s.nest and (g[6][s.nest[0]] < 1 or s.rf[s.nest[0]] < 1):
            s.nest = None
        if s.nest is None and s.nest_t <= 0 and s.season in ('spring', 'summer') and s.grown() and s.mature() > .02:
            s.nest_t = 5.0
            s.nest = s.pick_spot(g)

    def draw_ground_critters(s, buf, pp):
        for kind, c in s.gc.items():
            f, fy = c['dir'], float(s.tree.gnd(c['x'])) + s.ph * c['yo']
            ph_ = int(s.t * (7 if kind == 'fox' else 5)) % 2 if c['state'] == 'walk' else 0
            if kind == 'hedgehog':
                if c['state'] == 'stop' and int(s.t * 2) % 2:
                    f = -f
                px = [(-1, -1, HB), (0, -1, HB), (-1, -2, HL), (0, -2, HB), (0, -3, HL)] if c['state'] == 'curl' else \
                     [(x, -1, HB) for x in range(-2, 2)] + [(-2, -2, HB), (-1, -2, HL), (0, -2, HB), (1, -2, HL), (-1, -3, HL), (0, -3, HB),
                                                              (2, -1, (214, 184, 150)), (3, -1, FK), (2, -2, (214, 184, 150)), (-1 + ph_, 0, FK), (1 - ph_, 0, FK)]
            elif kind == 'fox':
                px = [(x, -3, FX) for x in range(-2, 2)] + [(-2, -2, FX), (-1, -2, FW), (0, -2, FW), (1, -2, FX), (2, -4, FX), (3, -4, FX),
                                                          (2, -3, FX), (3, -3, FX), (4, -3, FK), (2, -5, FX), (3, -5, FX), (-3, -4, FX), (-4, -4, FX),
                                                          (-5, -5, FX), (-6, -5, FW), (-3, -3, FX)]
                px += [(-2 + ph_, -1, FK), (1 - ph_, -1, FK), (-2 + ph_, 0, FK), (1 - ph_, 0, FK)]
                if c['state'] == 'stop':  # принюхивается: голова вниз
                    px = [(x, y + (1 if x >= 2 else 0), cc) for x, y, cc in px]
            else:
                px = [(-1, -2, (160, 116, 72)), (0, -2, (160, 116, 72)), (-1, -1, (160, 116, 72)), (0, -1, (160, 116, 72))] + \
                     [(x, 0, (200, 190, 160)) for x in range(-2, 3)] + [(2, -1, (200, 190, 160)), (3 if int(s.t) % 2 else 2, -2, (200, 190, 160))]
            for dx, dy, col in px:
                pp(c['x'], fy, dx * f, dy, col)

    def draw_nest(s, buf, pp):
        if not s.nest:
            return
        g = s.geom(s.progress())
        x, y = s.anchor(g, *s.nest)
        for dx, dy, col in ((-2, -1, NEST2), (-1, 0, NEST), (0, 0, NEST), (1, 0, NEST), (2, -1, NEST2), (-1, -1, NEST2), (1, -1, NEST2), (0, -1, NEST)):
            pp(x, y, dx, dy, col)
        if s.season == 'spring':
            for dx in (-1, 1):
                pp(x, y, dx, -1, (176, 214, 226))
        elif s.season == 'summer':
            for k, dx in enumerate((-1, 1)):
                pp(x, y, dx, -2, (226, 196, 140))
                if int(s.t * 3 + k * 2) % 4 == 0:   # просят есть: клюв открыт
                    pp(x, y, dx, -3, (255, 190, 50))

    def draw_critters(s, buf, tint):
        div = 1 / np.maximum(tint, .05)
        z = s.zs()

        def pp(x, y, dx, dy, c, a=1.0):
            s.put(buf, x + dx * z, y + dy * z - (z - 1), c, a, z)
        s.draw_nest(buf, pp)
        s.draw_ground_critters(buf, pp)
        o = s.owl
        if o:
            a = 1.0 if o['state'] == 'out' else min(1.0, (s.t - o['t0']) / 2)
            lift = np.minimum(2.2, div ** .5)   # ночью сову подсвечиваем, иначе её не видно
            B, P = np.minimum(255, np.array((104, 88, 74), np.float32) * lift), np.minimum(255, np.array((168, 146, 116), np.float32) * lift)
            E = B if (o['state'] == 'sit' and o['blink'] < 0) else np.array([255, 224, 70], np.float32) * div
            flap = int(s.t * 8) % 2 if o['state'] == 'out' else 0
            px = [(-1, -4, B), (1, -4, B), (-1, -3, E), (0, -3, (236, 150, 50)), (1, -3, E), (-1, -2, B), (0, -2, P), (1, -2, B),
                  (-1, -1, B), (0, -1, P), (1, -1, B), (-1, 0, B), (0, 0, P), (1, 0, B),
                  (-2, -2 - flap, B), (2, -2 - flap, B), (-2, -1 - flap, B), (2, -1 - flap, B)]
            for dx, dy, c in px:
                pp(o['x'], o['y'], dx, dy, c, a)
        q = s.squirrel
        if q:
            B, L, T = (150, 92, 48), (196, 138, 86), (178, 112, 60)
            if q['state'] in ('in', 'out'):
                f = -q['side'] if q['state'] == 'in' else q['side']
                px = [(0, 0, B), (-f, 0, B), (0, -1, B), (-f, -1, B), (f, -1, L), (f, -2, B), (2 * f, -1, (60, 40, 30)),
                      (-2 * f, -1, T), (-2 * f, -2, T), (-2 * f, -3, T), (-f, -4, T), (0, -3, T)]
                if int(s.t * 10) % 2:
                    px[1] = (-f, 1, B)  # лапы бегут
            else:
                sd = q['side']
                px = [(0, -2, B), (0, -1, B), (0, 0, B), (0, -3, L), (sd, -4, B), (sd, 0, T), (2 * sd, -1, T), (2 * sd, -2, T), (sd, -3, T)]
                if q['state'] == 'down':
                    px = [(dx, -3 - dy, c) for dx, dy, c in px]
            for dx, dy, c in px:
                pp(q['x'], q['y'], dx, dy, c)
        d = s.deer
        if d:
            f = d['dir']
            fy = float(s.tree.gnd(d['x'])) + s.ph * .045
            gz = d['state'] == 'graze'
            ph_ = int(s.t * 4.5) % 2 if d['state'] == 'walk' else 0
            px = [(x, -7, DEER_BODY) for x in range(6)] + [(x, -6, DEER_LIGHT) for x in range(6)] + [(-1, -7, (240, 234, 220))]
            for lx_, lift in ((0, ph_), (1, 1 - ph_), (4, 1 - ph_), (5, ph_)):  # ноги
                px += [(lx_, y, DEER_BODY) for y in range(-5, -lift if lift else 0)]
            if not gz:
                px += [(5, -8, DEER_BODY), (6, -9, DEER_BODY), (6, -10, DEER_BODY), (7, -10, DEER_BODY), (8, -10, DEER_BODY), (8, -9, DEER_LIGHT),
                       (7, -11, DEER_BODY), (7, -12, DEER_HORN), (8, -13, DEER_HORN), (6, -13, DEER_HORN)]
            else:
                px += [(6, -7, DEER_BODY), (7, -6, DEER_BODY), (7, -5, DEER_BODY), (8, -5, DEER_BODY), (9, -5, DEER_LIGHT),
                       (8, -6, DEER_HORN), (9, -7, DEER_HORN), (8, -8, DEER_HORN)]
            for dx, dy, c in px:
                s.put(buf, d['x'] + (dx - 4) * f * z, fy + dy * z, c, 1.0, z)

    def draw_fruit(s, buf):
        for x, y, _, c in s.drift:
            s.put(buf, x, y, c, 1.0, 2 if s.pw >= 120 else 1)
        tr = s.tree
        sz = 2 if s.ph >= 56 else 1
        if s.season in ('summer', 'autumn') and len(s.fr_i) and not s.gone:   # сгоревшее дерево плодов не роняет
            ripe = s.fruit_ripe()
            i = s.fr_i
            vis = (ripe > 0) & (s.progress() >= tr.lb[i]) & ~s.lcut[i] & ~s.sev[tr.lseg[i]]
            x = tr.lx[i] + s.wind_x(tr.lx[i], tr.ly[i], s.t)
            for j in np.where(vis)[0]:
                s.put(buf, x[j], tr.ly[i[j]], s.fruit_color(ripe[j] * (1.0 if s.season == 'autumn' else .55)), 1.0, sz)
        for x, y, _, c in s.fr_fall:
            s.put(buf, x, y, c, 1.0, sz)
        for x, c, _ in s.fr_gnd:
            s.put(buf, x, float(tr.gnd(x)) - sz, c, 1.0, sz)

    def draw_ground(s, buf):
        tr, pw = s.tree, s.pw
        gx = np.arange(pw, dtype=np.float32)
        gg = tr.gnd(gx)
        if s.season == 'winter' and s.snowd > .02:  # сугроб: вокруг ствола выше
            hh = s.snowd * (.9 + 2.4 * np.exp(-((gx - tr.cx) / (pw * .18)) ** 2)) * s.noise[0, :pw]
            a = np.clip(s.gyy - (gg - hh)[None, :] + .5, 0, 1) * (s.gyy < gg[None, :] + .5)
            buf[:] = buf * (1 - a[..., None]) + np.array([244, 248, 255], np.float32) * a[..., None]
        if s.pud > .03:
            sky = np.array([150, 180, 215], np.float32)
            for k, (px, py, a_, b_) in enumerate(s.puds):
                sc_ = .4 + .6 * s.pud
                x0, x1 = max(0, int(px - a_) - 1), min(pw, int(px + a_) + 2)
                y0, y1 = max(0, int(py - b_) - 2), min(s.ph, int(py + b_) + 3)
                if x1 <= x0 or y1 <= y0:
                    continue
                X, Y = s.gx[:, x0:x1], s.gyy[y0:y1]
                dd = ((X - px) / (a_ * sc_)) ** 2 + ((Y - py) / (b_ * sc_)) ** 2
                m = np.clip((1 - dd) * 3, 0, 1)[..., None] * min(1.0, s.pud * 1.5)
                g_ = float(tr.gnd(px))  # отражение: зеркально относительно линии земли, рябь сдвигает по x
                ys = np.clip((2 * g_ - Y - 1).astype(int), 0, s.ph - 1)
                xs = np.clip((X + np.round(np.sin(Y * 1.7 + s.t * 2 + k) * .7)).astype(int), 0, pw - 1)
                refl = buf[ys, xs] * .7 + sky * .3
                buf[y0:y1, x0:x1] = buf[y0:y1, x0:x1] * (1 - m * .8) + refl * m * .8
                if s.rain > .2:  # круги от капель
                    r = (s.t * 1.4 + k * .37) % 1.0
                    ring = np.clip(1 - np.abs(np.sqrt((X - px) ** 2 + ((Y - py) * (a_ / b_)) ** 2) - r * a_ * sc_ * .8) / .8, 0, 1)
                    buf[y0:y1, x0:x1] += (ring * (1 - r))[..., None] * m * 70
        if s.season != 'winter':  # трава качается на ветру; весной цветы, осенью грибы
            sway = np.sin(s.t * 1.7 + s.gr_x * .35) * min(1.6, .5 + .35 * s.wnow)
            base = np.array(SEASONS[s.season]['ground'][0], np.float32)
            g0 = tr.gnd(s.gr_x)
            for k in range(1, int(s.gr_h.max()) + 1):
                m = (s.gr_h >= k) & (s.gscorch[np.clip(s.gr_x.astype(int), 0, pw - 1)] < .35)   # в выжженной колонке травы нет
                ix = (s.gr_x[m] + np.round(sway[m] * k / s.gr_h[m])).astype(int)
                iy = (g0[m] - k).astype(int)
                ok = (ix >= 0) & (ix < pw) & (iy >= 0)
                ty = iy - s.trunk_y0
                ok &= ~((ty >= 0) & (ty < s.trunk_m.shape[0]) & s.trunk_m[np.clip(ty, 0, s.trunk_m.shape[0] - 1), np.clip(ix, 0, pw - 1)])   # не поверх ствола
                buf[iy[ok], ix[ok]] = np.minimum(255, base * s.gr_c[m][ok, None] * (1.0 + .07 * k))
            if s.season in ('spring', 'summer'):
                for j in np.where(s.gr_fl & ((s.gr_fc % 2 == 0) | (s.season == 'spring')))[0]:
                    if s.gscorch[min(max(int(s.gr_x[j]), 0), pw - 1)] >= .35:
                        continue
                    s.put(buf, s.gr_x[j] + round(float(sway[j])), g0[j] - s.gr_h[j] - 1, FLOWERS[s.gr_fc[j]])
            if s.season == 'autumn' and s.grown():
                age = min(1.0, (s.gt - s.grow_time * 1.12) / 90)
                for x, off in s.mush[:int(len(s.mush) * age + .999)]:
                    if s.gscorch[min(max(int(x), 0), pw - 1)] >= .35:
                        continue
                    y0 = float(tr.gnd(x)) - 1
                    s.put(buf, x, y0, (232, 222, 200))
                    for dx, c in ((-1, (200, 48, 40)), (0, (250, 244, 236)), (1, (200, 48, 40))):
                        s.put(buf, x + dx, y0 - 1, c)
                    s.put(buf, x, y0 - 2, (200, 48, 40))

    def draw_sky_day(s, buf):
        """Солнце, радуга, облака — до листвы и освещения."""
        ph, pw = s.ph, s.pw
        grey = min(1.0, max(s.rain, s.storm))
        cover = float(np.clip(.3 + .7 * min(1.0, max(s.rain, s.storm * 1.2)) - .2 * s.fog, 0, 1))
        k = float(np.clip(1 - s.lt_night / .5, 0, 1)) * (1 - .9 * s.fog) * (1 - .9 * grey) * (1 - .45 * cover)
        dk = float(np.clip(1.25 - 1.3 * s.lt_night, 0, 1))  # день — светлое небо, ночью остаётся фон панели
        if dk > .02:
            v = np.clip(s.gyy / (ph * .86), 0, 1) ** 1.2
            top = np.array([96, 150, 222], np.float32) * (1 - grey) + np.array([118, 126, 140], np.float32) * grey
            hor = np.array([176, 212, 238], np.float32) * (1 - grey) + np.array([158, 164, 174], np.float32) * grey
            sky = top + (hor - top) * v[..., None]
            warm = 4 * s.lt_night * (1 - s.lt_night) * (1 - grey)  # закат/рассвет: тёплый горизонт, сиреневый верх
            if warm > .02:
                vv = v[..., None]
                dusk = np.where(vv < .55, np.array([84, 86, 158], np.float32) + (np.array([226, 112, 120], np.float32) - np.array([84, 86, 158], np.float32)) * (vv / .55),
                                np.array([226, 112, 120], np.float32) + (np.array([255, 196, 118], np.float32) - np.array([226, 112, 120], np.float32)) * ((vv - .55) / .45))
                sky = sky * (1 - .85 * warm) + dusk / np.maximum(s.tint()[None, None, :], .3) * .85 * warm
            m = (dk * .94 * (1 - s.gmask[..., 0]))[..., None]
            buf[:] = buf * (1 - m) + sky * m
        s.sun = None
        if k > .03:
            if s.tod_name == 'auto':
                u = min(1.0, max(0.0, (s.hour() - 6) / 14))
            else:
                u = .35 if s.tod_name == 'day' else .92
            sx, sy = s.pw * (.12 + .76 * u), s.ph * (.30 - .20 * math.sin(math.pi * u))
            R = max(2.5, ph * .035)
            d2 = (s.gx - sx) ** 2 + (s.gyy - sy) ** 2
            disk = np.clip(R + .5 - np.sqrt(d2), 0, 1)[..., None]
            buf += np.exp(-d2 / (4 * R) ** 2)[..., None] * np.array([255, 225, 160], np.float32) * .16 * k
            buf[:] = buf * (1 - disk * k) + np.array([255, 240, 185], np.float32) * disk * k
            s.sun = (sx, sy, k)
        if s.rb:
            a = max(0.0, min(1.0, (s.t - s.rb[0]) / 6, (40 - (s.t - s.rb[0])) / 12, (.45 - s.lt_night) / .15))
            R, bw = min(pw * .42, ph * .62), max(1.3, ph * .015)
            cy = float(s.tree.gnd(s.rb[1])) + ph * .1
            d = np.sqrt((s.gx - s.rb[1]) ** 2 + (s.gyy - cy) ** 2)
            u = np.clip((d - (R - 7 * bw)) / (7 * bw), 0, 1)
            col = np.stack([np.interp(u * 6, np.arange(7), RAINBOW[:, c]) for c in range(3)], -1)
            edge = np.clip(1 - np.abs(d - (R - 3.5 * bw)) / (3.5 * bw), 0, 1) ** .35
            m = (edge * .5 * max(a, 0) * (1 - s.gmask[..., 0]))[..., None]
            buf[:] = buf * (1 - m) + col * m
        n = cover * 5
        col = np.array([248, 248, 252], np.float32) * (1 - grey) + np.array([138, 146, 160], np.float32) * grey
        for i, c in enumerate(s.clouds):
            a = float(np.clip(n - i, 0, 1))
            if a < .02:
                continue
            w, h = c['w'], c['h']
            cx = (c['x'] + c['v'] * s.t) % (pw + 2 * w) - w
            x0, x1 = max(0, int(cx - w * .8)), min(pw, int(cx + w * .8) + 1)
            y0, y1 = max(0, int(c['y'] - h * 1.6)), min(ph, int(c['y'] + h * 1.2) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            X, Y = s.gx[:, x0:x1], s.gyy[y0:y1]
            m = 0
            for px, py, rx, ry in ((cx - .35 * w, c['y'] + .1 * h, .35 * w, .7 * h), (cx, c['y'] - .2 * h, .4 * w, h),
                                   (cx + .35 * w, c['y'] + .1 * h, .3 * w, .65 * h)):
                m = np.maximum(m, np.clip((1 - ((X - px) / rx) ** 2 - ((Y - py) / ry) ** 2) * 2.2, 0, 1))
            m = m * np.clip(c['y'] + .55 * h - Y, 0, 1)
            al = (m * a * (.55 + .35 * grey) * (1 - .5 * s.lt_night))[..., None]
            shade = (1 - .12 * np.clip((Y - c['y']) / h, -1, 1))[..., None]
            buf[y0:y1, x0:x1] = buf[y0:y1, x0:x1] * (1 - al) + col * shade * al

    def draw_rays(s, buf):
        """Лучи солнца поверх кроны (до освещения)."""
        if not s.sun or s.sun[2] < .15 or s.rain > .3:
            return
        sx, sy, k = s.sun
        key = (round(sx), round(sy), s.pw, s.ph)
        if getattr(s, 'ray_key', None) != key:
            dx, dy = s.gx - sx, s.gyy - sy
            s.ray_ang = np.arctan2(dy, dx)
            s.ray_fall = (np.exp(-np.sqrt(dx * dx + dy * dy) / (.9 * s.ph)) * (dy > 0)).astype(np.float32)
            s.ray_key = key
        r = (np.sin(s.ray_ang * 9 + s.t * .15) * .5 + .5) ** 4
        buf += (r * s.ray_fall * .09 * k * (1 - .5 * s.gmask[..., 0]))[..., None] * np.array([255, 232, 175], np.float32)

    def scare(s, x, y, R):
        for b in s.birds:
            if b.state != 'out' and math.hypot(b.x - x, b.y - y) < R:
                b.leave(s.pw)
        o = s.owl
        if o and o['state'] == 'sit' and math.hypot(o['x'] - x, o['y'] - y) < R:
            o['state'], o['vx'], o['vy'] = 'out', o['face'] * 18, -9
        q = s.squirrel
        if q and math.hypot(q['x'] - x, q['y'] - y) < R * 1.3:
            q['state'] = 'down' if q['state'] in ('climb', 'sit') else 'out' if q['state'] == 'in' else q['state']
        d = s.deer
        if d and abs(d['x'] - x) < R * 1.5:
            d['flee'], d['state'] = True, 'walk'
        for kind, c in s.gc.items():
            if abs(c['x'] - x) < R * 1.5 and y > float(s.tree.gnd(c['x'])) - 6 * s.zs():
                if kind == 'fox':
                    c['flee'], c['state'] = True, 'walk'
                else:  # ёж сворачивается в клубок, улитка прячется
                    c['state'], c['wait'] = 'curl', 6.0


    def tint(s):
        """Цвет освещения с учётом пасмурности."""
        return np.clip(s.lt_tint * (1 - .22 * min(1.0, max(s.rain, s.storm * 1.2))), .05, 1.2)

    def draw(s):
        tr, ph, pw, t = s.tree, s.ph, s.pw, s.t
        buf = s.base.copy()
        tint = s.tint()
        s.draw_sky(buf, tint)
        s.draw_sky_day(buf)
        s.draw_backdrop(buf)
        G = s.progress()
        if s.cols is not None:
            lv = s.leaf_pos(G)
        # задние листья
        if s.cols is not None:
            s.plot(buf, lv, back=True)
        s.draw_particles(buf, back=True)
        s.draw_particles(buf)       # опавшая листва — слой земли, ствол стоит поверх неё
        pre = buf.copy() if s.sharp else None
        sy0 = max(0, int(tr.gy - tr.mound) - 2 * int(s.gr_h.max()) - 4)   # полоса у земли: где ствол, там травы нет
        pre_strip = buf[sy0:].copy()
        s.draw_saps(buf)
        s.draw_bark(buf, G)
        if s.cols is not None:
            s.plot(buf, lv, back=False)
        if s.sharp:
            s.tmask = (buf != pre).any(-1)
        s.trunk_y0, s.trunk_m = sy0, (buf[sy0:] != pre_strip).any(-1)
        s.draw_deco(buf)
        s.draw_rays(buf)
        s.draw_pieces(buf)
        s.draw_logs(buf)
        s.draw_particles(buf, back=False)
        s.draw_ground(buf)
        s.draw_stump(buf, s.geom(G))
        s.draw_fruit(buf)
        s.draw_chips(buf)
        s.draw_fauna(buf)
        s.draw_critters(buf, tint)
        buf *= tint
        s.draw_fire(buf)
        s.draw_fire_fx(buf)
        s.draw_bd_lights(buf)
        if s.wet > .02:
            buf *= 1 - .22 * s.wet * s.gmask
        s.draw_weather(buf, tint)
        s.sharpen(buf)
        s.draw_slash(buf)
        s.draw_hud(buf)
        return np.clip(buf, 0, 255).astype(np.uint8)

    @staticmethod
    def boxblur(a, r):
        """Размытие окном (2r+1)² через накопленные суммы; a — (h, w[, c])."""
        c = np.pad(a, [(r, r), (r, r)] + [(0, 0)] * (a.ndim - 2), mode='edge').cumsum(0).cumsum(1)
        c = np.pad(c, [(1, 0), (1, 0)] + [(0, 0)] * (a.ndim - 2))
        n = 2 * r + 1
        return (c[n:, n:] - c[:-n, n:] - c[n:, :-n] + c[:-n, :-n]) / (n * n)

    def sharpen(s, buf):
        """Чёткость (убирает «мыло»): 1) локальный контраст с большим радиусом — листва и холмы перестают сливаться;
        2) дерево (маска s.tmask из draw) получает свой контраст — тёмное темнее, светлое светлее;
        3) фон вокруг кроны чуть притемняется мягким ореолом, дерево отрывается от него."""
        if not s.sharp:
            return
        k = s.sharp / SHARP_MAX
        r = max(3, min(9, s.ph // 14))
        lum = buf @ np.array([.3, .59, .11], np.float32)   # контраст только по яркости — оттенки не плывут
        d = np.clip((lum - s.boxblur(lum, r)) * (.9 * k) + (lum - s.boxblur(lum, 1)) * (.4 * k), -34 * k - 4, 34 * k + 4)
        m = s.tmask.astype(np.float32)
        if m.any():
            d += (lum - lum[m > 0].mean()) * (.2 * k) * m   # дерево: тёмное темнее, светлое светлее
            d -= 16 * k * np.clip(s.boxblur(m, 3) * 2.2, 0, 1) * (1 - m)   # мягкий тёмный ореол вокруг кроны — отрыв от фона
        buf += d[..., None] * (buf / np.maximum(lum, 8)[..., None]).clip(.4, 2.2)   # дельта пропорциональна цвету: серых пятен нет
        v = float(np.percentile(lum[::2, ::2], 4)) * .5 * k   # вуаль (туман, дымка): сдвигаем чёрную точку кадра и растягиваем остальное
        buf[:] = (buf - v) / (1 - v / 255)

    def draw_sky(s, buf, tint):
        """Звёзды и луна: рисуются до освещения, поэтому делятся на tint, чтобы остаться яркими."""
        k = np.clip((s.lt_night - .25) / .6, 0, 1) * (1 - .8 * s.fog) * (1 - .6 * s.rain)
        if k < .02:
            return
        div = 1 / np.maximum(tint, .05)
        sx, sy, br, ph = s.stars
        v = br * (.65 + .35 * np.sin(s.t * 1.4 + ph)) * k * 150
        buf[sy, sx] += v[:, None] * div[None, :]
        if s.aurora:
            s.draw_aurora(buf, div)
        for m in s.meteors:
            a = (s.t - m['t0']) / 1.0
            for j in range(12):  # голова и хвост
                u = a - j * .018
                if u < 0:
                    continue
                s.put(buf, m['x'] + m['vx'] * u, m['y'] + m['vy'] * u, np.array([235, 240, 255], np.float32) * div,
                      max(0.0, (1 - j / 12) * (1 - a) * k))
        R = max(3.0, s.ph * .045)
        if s.tod_name == 'auto':
            u = ((s.hour() - 19) % 24) / 11
            u = min(1.0, max(0.0, u))
        else:
            u = .7
        mx, my = round(s.pw * (.15 + .7 * u), 1), round(s.ph * (.30 - .18 * math.sin(math.pi * u)), 1)
        key = (mx, my, round(float(k), 3), tuple(np.round(div, 2)), s.pw, s.ph)
        if getattr(s, 'moon_key', None) != key:  # луна почти не двигается — слой считаем только при изменении
            d2 = (s.gx - mx) ** 2 + (s.gyy - my) ** 2
            disk = np.clip(R + .5 - np.sqrt(d2), 0, 1)
            bite = np.clip(R * .9 + .5 - np.sqrt((s.gx - mx - R * .5) ** 2 + (s.gyy - my + R * .2) ** 2), 0, 1)
            cov = (disk * (1 - bite) * k)[..., None]
            glow = (np.exp(-d2 / (3 * R) ** 2) * .09 * k)[..., None]
            s.moon_add = (np.array([238, 238, 210], np.float32) * cov + np.array([200, 210, 255], np.float32) * glow) * div
            s.moon_key = key
        buf += s.moon_add

    def draw_aurora(s, buf, div):
        a0, dur = s.aurora
        age = s.t - a0
        f = min(1.0, age / 6, (dur - age) / 8) * float(np.clip((s.lt_night - .7) / .25, 0, 1)) * (1 - s.fog) * (1 - s.rain)
        if f < .02:
            return
        X, Y = s.gx, s.gyy
        c = s.ph * (.24 + .05 * np.sin(X * .07 + s.t * .25) + .03 * np.sin(X * .17 - s.t * .4))
        d = (c - Y) / (s.ph * .22)  # >0 выше нижней кромки занавеса
        prof = np.where(d < 0, np.exp(d * 6), np.exp(-d * 1.6))
        rays = (np.sin(X * 1.1 + 2 * np.sin(s.t * .5 + X * .13)) * .5 + .5) ** 1.5
        a = prof * (.3 + .7 * rays) * (.55 + .45 * np.sin(X * .05 + s.t * .3)) * f * 1.7 * (1 - s.gmask[..., 0])
        mix = np.clip(d * .6, 0, 1)[..., None]
        col = np.array([70, 255, 150], np.float32) * (1 - mix) + np.array([160, 90, 235], np.float32) * mix
        buf += a[..., None] * col * div

    def draw_fauna(s, buf):
        def put(x, y, c):
            ix, iy = int(round(x)), int(round(y))
            if 0 <= ix < s.pw and 0 <= iy < s.ph:
                buf[iy, ix] = c
        for b in s.birds:
            B, P, f = b.back, b.belly, b.face
            if b.state == 'perch':
                px = [(1, -2, B), (2, -2, B), (-2, -1, B), (-1, -1, B), (0, -1, B), (1, -1, P), (2, -1, P),
                      (0, 0, P), (1, 0, P), (3, -2, (230, 170, 60))]
            else:
                up = int(s.t * 9 + id(b)) % 2 == 0
                px = [(-1, 0, B), (0, 0, B), (1, 0, P), (2, 0, B)]
                px += [(-1, -1, B), (-2, -2, B), (0, -1, B), (1, -2, B)] if up else [(-1, 1, B), (-2, 1, B), (0, 1, B), (1, 2, B)]
            for dx, dy, c in px:
                put(b.x + dx * f, b.y + dy, c)
        for q in s.bflies:
            open_ = int(s.t * 8 + q['ph']) % 2 == 0
            put(q['x'], q['y'], (60, 50, 50))
            if open_:
                put(q['x'] - 1, q['y'], q['col'])
                put(q['x'] + 1, q['y'], q['col'])
            else:
                put(q['x'], q['y'] - 1, q['col'])

    def draw_weather(s, buf, tint):
        lum = float(tint.mean())
        if s.fog > .02:
            a = s.fog * np.clip(.30 + .35 * s.gyy / s.ph + .12 * (np.sin(s.gx * .07 + s.t * .22) + np.sin(s.gyy * .11 - s.t * .13 + s.gx * .03)), 0, .85)
            fogc = np.array([172, 184, 196], np.float32) * (.25 + .75 * lum)
            buf[:] = buf * (1 - a[..., None]) + fogc * a[..., None]
        # светлячки: тихая тёплая ночь
        fk = float(np.clip((s.lt_night - .35) / .4, 0, 1)) * (1 - min(1.0, s.rain * 2))
        if fk > .02:
            rng = np.random.default_rng(11)
            for i in range(16):
                bx, by = rng.uniform(.1, .9) * s.pw, rng.uniform(.45, .84) * s.ph
                w1, w2, p1, p2, pb = rng.uniform(.3, .7), rng.uniform(.3, .7), rng.uniform(0, 6.28), rng.uniform(0, 6.28), rng.uniform(0, 6.28)
                x = bx + 6 * math.sin(w1 * s.t + p1)
                y = by + 4 * math.sin(w2 * s.t + p2)
                v = max(0.0, math.sin(s.t * 1.1 + pb) * 1.4) ** 2 * fk
                ix, iy = int(x), int(y)
                if v > .05 and 1 <= ix < s.pw - 1 and 1 <= iy < s.ph - 1:
                    c = np.array([190, 255, 110], np.float32)
                    buf[iy, ix] += c * v
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        buf[iy + dy, ix + dx] += c * v * .25
        if len(s.rx):
            rc = np.array([165, 182, 214], np.float32) * (.45 + .55 * lum)
            for k in range(3):  # капля — короткая наклонная черта
                ix = np.round(s.rx - k * (4 * s.wnow + 10 * s.storm) / np.maximum(s.rv, 1) * 1.0).astype(int)
                iy = np.round(s.ry - k).astype(int)
                ok = (ix >= 0) & (ix < s.pw) & (iy >= 0) & (iy < s.ph)
                buf[iy[ok], ix[ok]] = buf[iy[ok], ix[ok]] * (1 - .5 / (k + 1)) + rc * (.5 / (k + 1))
        for x, y, t0 in s.splash:
            a = 1 - (s.t - t0) / .22
            ix, iy = int(x), int(y)
            for dx, dy in ((-1, 0), (1, 0), (0, -1)):
                if 0 <= ix + dx < s.pw and 0 <= iy + dy < s.ph:
                    buf[iy + dy, ix + dx] += np.array([150, 170, 200], np.float32) * (.4 * a * (.5 + .5 * lum))
        if s.bolt:
            for (ax, ay), (bx, by) in zip(s.bolt[1][:-1], s.bolt[1][1:]):
                n = max(2, int(math.hypot(bx - ax, by - ay) / .5))
                u = np.linspace(0, 1, n)
                ix, iy = (ax + (bx - ax) * u).astype(int), (ay + (by - ay) * u).astype(int)
                ok = (ix >= 0) & (ix < s.pw) & (iy >= 0) & (iy < s.ph)
                buf[iy[ok], ix[ok]] = (235, 240, 255)
        if s.flash > .02:
            buf += s.flash * 55

    def leaf_pos(s, G):
        tr = s.tree
        vis = (G >= tr.lb) & (s.gt > 0) & ~s.lcut & ~s.sev[tr.lseg] & (tr.lfull < .78 + .22 * s.mature())
        x = tr.lx[vis] + s.wind_x(tr.lx[vis], tr.ly[vis], s.t) + .35 * np.sin(4.2 * s.t + tr.lph[vis])
        y = tr.ly[vis] + .25 * np.sin(3.1 * s.t + tr.lph[vis] * 1.7)
        col = s.cols[vis]
        u = np.minimum(np.clip((G - tr.lb[vis]) / (.12 * tr.maxb), 0, 1), np.clip((s.gt - s.lborn[vis]) / 30, 0, 1))[:, None]  # новые листья сначала светло-зелёные
        if (u < 1).any():
            fresh = np.array([140, 205, 85], np.float32) * (col.mean(1, keepdims=True) / 110)
            col = fresh * (1 - u) + col * u
        return vis, x, y, col

    def plot(s, buf, lv, back):
        vis, x, y, col = lv
        sel = s.tree.back[vis] == back
        ix, iy = np.round(x[sel]).astype(int), np.round(y[sel]).astype(int)
        ok = (ix >= 0) & (ix < s.pw) & (iy >= 0) & (iy < s.ph)
        s.splat(buf, ix[ok], iy[ok], col[sel][ok])

    def splat(s, buf, ix, iy, c):
        sz = 2 if s.pw >= 120 else 1
        for dy in range(sz):
            for dx in range(sz):
                yy, xx = np.minimum(iy + dy, s.ph - 1), np.minimum(ix + dx, s.pw - 1)
                buf[yy, xx] = c

    def draw_bark(s, buf, G):
        x0, y0, x1, y1, r0, r1, f = s.geom(G)
        m = f > 0
        s.stroke(buf, x0[m], y0[m], x1[m], y1[m], r0[m], r1[m], True)
        s.draw_scars(buf, (x0, y0, x1, y1, r0, r1, f))

    def bark_col(s):
        P = s.tree.P
        return np.array(P['bark'] if 'bark' in P and s.season != 'winter' else SEASONS[s.season]['bark'], np.float32)

    def stroke(s, buf, x0, y0, x1, y1, r0, r1, snow, col=None):
        bark = s.bark_col() if col is None else np.asarray(col, np.float32)
        thick = np.maximum(r0, r1) >= 1.05
        # тонкие: семплы вдоль отрезка, билинейный сплат
        ti = np.where(~thick)[0]
        if len(ti):
            ln = np.hypot(x1[ti] - x0[ti], y1[ti] - y0[ti])
            ns = np.maximum(2, np.ceil(ln * 1.6).astype(int))
            sid = np.repeat(np.arange(len(ti)), ns)
            u = (np.arange(ns.sum()) - np.repeat(np.cumsum(ns) - ns, ns)) / np.repeat(np.maximum(ns - 1, 1), ns)
            k = ti[sid]
            px = x0[k] + (x1[k] - x0[k]) * u
            py = y0[k] + (y1[k] - y0[k]) * u
            rr = r0[k] + (r1[k] - r0[k]) * u
            wgt = np.clip(rr * 2.0, .45, 1.0)
            fx, fy = px - .5, py - .5
            ix, iy = np.floor(fx).astype(int), np.floor(fy).astype(int)
            ax, ay = fx - ix, fy - iy
            col = bark * (1.1 - .35 * (py / s.ph))[:, None]
            fi, fw, fc = [], [], []
            for dx, dy, w in ((0, 0, (1 - ax) * (1 - ay)), (1, 0, ax * (1 - ay)), (0, 1, (1 - ax) * ay), (1, 1, ax * ay)):
                xx, yy = ix + dx, iy + dy
                ok = (xx >= 0) & (xx < s.pw) & (yy >= 0) & (yy < s.ph)
                ww = (w * wgt)[ok]
                fi.append(yy[ok] * s.pw + xx[ok])
                fw.append(ww)
                fc.append(ww[:, None] * col[ok])
            fi, fw, fc = np.concatenate(fi), np.concatenate(fw), np.concatenate(fc)
            n = s.ph * s.pw  # bincount вместо np.add.at: в разы быстрее
            wacc = np.bincount(fi, fw, minlength=n).astype(np.float32).reshape(s.ph, s.pw)
            cacc = np.bincount((fi[:, None] * 3 + np.arange(3)).ravel(), fc.ravel(), minlength=n * 3).astype(np.float32).reshape(s.ph, s.pw, 3)
            mm = np.minimum(wacc * 1.25, 1.0)[..., None]
            cc = cacc / np.maximum(wacc, 1e-6)[..., None]
            buf[:] = buf * (1 - mm) + cc * mm
        if snow and s.season == 'winter' and s.grown():
            sel = np.where((np.abs(y1 - y0) < np.abs(x1 - x0) * 1.6 + .5) & (r0 < 2.4))[0][::2]
            sel = sel[(sel * .618) % 1 < .2 + .8 * s.snowd]  # снега на ветках всё больше
            if len(sel):
                u = np.linspace(.15, .85, 4)[None, :]
                sx = (x0[sel, None] + (x1[sel] - x0[sel])[:, None] * u).ravel()
                sy = (y0[sel, None] + (y1[sel] - y0[sel])[:, None] * u).ravel() - np.repeat(np.maximum(r0[sel], .5), 4) - .2
                ix, iy = np.round(sx - .5).astype(int), np.round(sy - .5).astype(int)
                ok = (ix >= 0) & (ix < s.pw) & (iy >= 0) & (iy < s.ph)
                buf[iy[ok], ix[ok]] = buf[iy[ok], ix[ok]] * .25 + np.array([240, 246, 255], np.float32) * .75
        # толстые: поле расстояний, освещение слева-сверху. Расстояния считаются пачкой для всех отрезков сразу,
        # а накладываются по очереди, чтобы порядок перекрытий остался прежним
        ti = np.where(thick)[0]
        if not len(ti):
            return
        a0, b0, a1, b1, ra, rb = x0[ti], y0[ti], x1[ti], y1[ti], r0[ti], r1[ti]
        pad = np.maximum(ra, rb) + 1.5
        xa = np.maximum(0, np.minimum(a0, a1) - pad).astype(int)
        xb = np.minimum(s.pw, np.maximum(a0, a1) + pad + 1).astype(int)
        ya = np.maximum(0, np.minimum(b0, b1) - pad).astype(int)
        yb = np.minimum(s.ph, np.maximum(b0, b1) + pad + 1).astype(int)
        ok = (xa < xb) & (ya < yb)
        if not ok.any():
            return
        a0, b0, a1, b1, ra, rb, xa, xb, ya, yb = (v[ok] for v in (a0, b0, a1, b1, ra, rb, xa, xb, ya, yb))
        wi, hi = xb - xa, yb - ya
        K = int(max(wi.max(), hi.max()))
        ar = np.arange(K)
        X = ((xa[:, None] + ar) + .5).astype(np.float32)[:, None, :]
        Y = ((ya[:, None] + ar) + .5).astype(np.float32)[:, :, None]
        dx, dy = (a1 - a0)[:, None, None], (b1 - b0)[:, None, None]
        a0, b0, ra, rb = a0[:, None, None], b0[:, None, None], ra[:, None, None], rb[:, None, None]
        tt = np.minimum(np.maximum(((X - a0) * dx + (Y - b0) * dy) / (dx * dx + dy * dy + 1e-9), 0), 1)
        ox, oy = X - (a0 + tt * dx), Y - (b0 + tt * dy)
        r = ra + (rb - ra) * tt
        valid = (ar[None, None, :] < wi[:, None, None]) & (ar[None, :, None] < hi[:, None, None])
        cov = np.minimum(np.maximum(r + .5 - np.hypot(ox, oy), 0), 1) * valid
        shade = np.minimum(np.maximum((ox + oy) * (-.7) / np.maximum(r, .5), -1), 1)
        ny = np.minimum(ya[:, None] + ar, s.ph - 1)[:, :, None]
        nx = np.minimum(xa[:, None] + ar, s.pw - 1)[:, None, :]
        col = bark * (1 + .28 * shade)[..., None] * s.noise[ny, nx][..., None]
        cov = cov[..., None]
        for i in range(len(xa)):
            w, h = wi[i], hi[i]
            sub = buf[ya[i]:yb[i], xa[i]:xb[i]]
            c = cov[i, :h, :w]
            sub[:] = sub * (1 - c) + col[i, :h, :w] * c

    # ---------- листопад ----------
    def advance(s, dt):
        s.t += dt
        s.gt += dt * SPEEDS[s.spd]
        if s.tl is not None:
            s.step_timelapse(dt)
        s.update_rf()
        s.update_env(dt)
        s.update_fauna(dt)
        s.update_extras(dt)
        s.lacc += dt
        if s.lacc >= .5:
            s.lacc = 0.0
            s.regrow_leaves()
        cfg = SEASONS[s.season]
        tr = s.tree
        auto = bool(cfg['fall']) and s.grown() and not (s.cols is None and cfg['fall'] != 'snow')
        rate = (4.0 if cfg['fall'] != 'snow' else 14.0) * s.pw / 80
        n = np.random.poisson(rate * dt) if auto else 0
        if n:
            rng = np.random.default_rng()
            if cfg['fall'] == 'snow':
                nx = rng.uniform(0, s.pw, n)
                ny = np.full(n, -1.0)
                nc = np.tile(np.array(cfg['fcol'], np.float32), (n, 1))
            else:
                k = rng.integers(0, len(tr.lx), n)
                k = k[~s.lcut[k] & ~s.sev[tr.lseg[k]] & (tr.lb[k] <= s.progress()) & (tr.lfull[k] < .78 + .22 * s.mature())]
                n = len(k)
                nx = tr.lx[k] + s.wind_x(tr.lx[k], tr.ly[k], s.t)
                ny = tr.ly[k].astype(np.float64)
                nc = s.cols[k] * 1.1 if cfg['fall'] == 'leaf' else np.tile(np.array(cfg['fcol'], np.float32), (n, 1))
            s.add_particles(nx, ny, nc, rng.uniform(3, 7, n) * (.6 if cfg['fall'] == 'snow' else 1))
        for p in s.pieces:
            p.step(dt, s)
            if p.landed:
                p.landed = False
                s.crash(p)
        s.pieces = [p for p in s.pieces if p.alpha > .02]
        s.update_chips(dt)
        s.update_fire(dt)
        s.sprout_fruit(dt)
        s.slash = [(p, t0) for p, t0 in s.slash if s.t - t0 < .4]
        if len(s.fx):
            s.fvy += (s.fvt - s.fvy) * min(1.0, 2.5 * dt)
            s.fy += s.fvy * dt
            s.fx += (np.sin(s.fph + s.t * 1.8) * 5 + 2.5 * s.wnow + s.fvx) * dt
            # листья не ползут по стволу: передние обтекают его, задние пусть скрывает кора
            tx, hw = float(tr.S[0, 0]), float(tr.S[0, 4]) + 1.2
            dx = s.fx - tx
            near = (s.fz >= .5) & (np.abs(dx) < hw + 1.5) & (s.fy > tr.gy - tr.th * .9)
            if near.any():
                s.fx[near] += np.tanh(dx[near] * 1.5) * (hw + 1.5 - np.abs(dx[near])) * min(1.0, 8 * dt)
            s.fvx *= math.exp(-2.2 * dt)
            hit = s.fy >= tr.gnd(s.fx) - .5
            if hit.any() and cfg['fall'] != 'snow':  # снег копится сугробом (draw_ground), а не слоем снежинок
                s.land_leaves(s.fx[hit], s.fc[hit])
            del s.litter[:-int(s.pw * 3)]
            keep = ~hit & (s.fx > -2) & (s.fx < s.pw + 2)
            s.fx, s.fy, s.fvy, s.fph, s.fc, s.fvx = s.fx[keep], s.fy[keep], s.fvy[keep], s.fph[keep], s.fc[keep], s.fvx[keep]
            s.fvt, s.fz = s.fvt[keep], s.fz[keep]

    def draw_pieces(s, buf):
        for p in s.pieces:
            x0, y0, x1, y1, lx, ly = p.world()
            if p.log:   # упавшее дерево: что ниже земли — под землёй, не рисуем
                keep = buf.copy()
            if p.alpha < 1:
                dst, buf = buf, buf.copy()
            s.stroke(buf, x0, y0, x1, y1, p.r0, p.r1, False)
            if p.alpha < 1:
                dst[:] = dst * (1 - p.alpha) + buf * p.alpha
                buf = dst
            if len(lx) and s.cols is not None:
                ix, iy = np.round(lx).astype(int), np.round(ly).astype(int)
                ok = (ix >= 0) & (ix < s.pw) & (iy >= 0) & (iy < s.ph)
                s.splat(buf, ix[ok], iy[ok], (p.lc * (1 - .45 * min(1.0, p.age / 200)) if p.log else p.lc)[ok])
            if p.log:
                under = s.gyy > s.tree.gnd(np.arange(s.pw, dtype=np.float32))[None, :] + .3
                buf[under] = keep[under]

    def draw_slash(s, buf):
        lines = [(p, 1.0) for p, _ in s.slash[:0]]
        lines = [(p, max(0.0, 1 - (s.t - t0) / .4)) for p, t0 in s.slash]
        if s.drag and len(s.drag) > 1:
            lines.append((s.drag, 1.0))
        for path, a in lines:
            for (ax, ay), (bx, by) in zip(path[:-1], path[1:]):
                n = max(2, int(math.hypot(bx - ax, by - ay) / .5))
                u = np.linspace(0, 1, n)
                ix, iy = (ax + (bx - ax) * u).astype(int), (ay + (by - ay) * u).astype(int)
                ok = (ix >= 0) & (ix < s.pw) & (iy >= 0) & (iy < s.ph)
                buf[iy[ok], ix[ok]] = buf[iy[ok], ix[ok]] * (1 - .85 * a) + 255 * .85 * a

    def land_leaves(s, xs, cs):
        """Опавшие листья собираются в кучки: тянутся к соседней куче, скатываются с крутой, у ствола не лежат."""
        pw = s.pw
        cnt = np.zeros(pw, int)
        if s.litter:
            np.add.at(cnt, np.clip([int(x) for x, _ in s.litter], 0, pw - 1), 1)
        tx, hw = float(s.tree.S[0, 0]), float(s.tree.S[0, 4]) + 1.5
        top = 7
        for x, c in zip(xs, cs):
            i = int(min(max(x, 0), pw - 1))
            if abs(i - tx) < hw:                      # ствол: откатиться в сторону
                i = int(tx + (hw if i >= tx else -hw))
            lo, hi = max(0, i - 4), min(pw, i + 5)
            w = np.where(cnt[lo:hi] < top, cnt[lo:hi], -1) + np.random.uniform(0, .9, hi - lo)
            j = lo + int(np.argmax(w))
            if 2 <= cnt[j] < top and random.random() < .55 and abs(j - tx) >= hw:
                i = j                                 # к соседней куче
            for _ in range(top * 2):                  # осыпание: склон не круче 1 листа на колонку — куча получается холмиком
                nb = [k for k in (i - 1, i + 1) if 0 <= k < pw and abs(k - tx) >= hw and cnt[k] < cnt[i]]
                if not nb or (cnt[i] - min(cnt[k] for k in nb) < 2 and cnt[i] < top):
                    break
                i = min(nb, key=lambda q: cnt[q] + random.random() * .5)
            if cnt[i] >= top:                         # вершина полна и скатиться некуда: лист не добавляется
                continue
            i = min(max(i, 0), pw - 1)
            cnt[i] += 1
            s.litter.append((i + .5, c))

    def draw_particles(s, buf, back=None):
        if len(s.fx) and back is not None:
            m = (s.fz < .5) == back
            ix, iy = s.fx[m].astype(int), s.fy[m].astype(int)
            ok = (ix >= 0) & (ix < s.pw) & (iy >= 0) & (iy < s.ph)
            buf[iy[ok], ix[ok]] = s.fc[m][ok]
        if s.litter and back is None:
            lx = np.array([int(x) for x, _ in s.litter])
            lc = np.array([c for _, c in s.litter])
            o = np.argsort(lx, kind='stable')   # листья ложатся слоями: до 3 рядов, новые сверху
            lx, lc = lx[o], lc[o]
            first = np.r_[0, np.flatnonzero(np.diff(lx)) + 1]
            lvl = np.minimum(np.arange(len(lx)) - np.repeat(first, np.diff(np.r_[first, len(lx)])), 7)
            ly = np.round(s.tree.gnd(lx.astype(np.float32))).astype(int) - 1 - lvl
            ok = (lx >= 0) & (lx < s.pw) & (ly >= 0)
            buf[ly[ok], lx[ok]] = lc[ok]


# ---------- вывод ----------
def save_png(path, arr, scale=1):
    if scale > 1:
        arr = np.repeat(np.repeat(arr, scale, 0), scale, 1)
    h, w, _ = arr.shape
    raw = b''.join(b'\x00' + arr[y].tobytes() for y in range(h))

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
                chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


class Screen:
    """Дифф кадра в полублоки: ячейка = 2 пикселя по вертикали (▀ fg=верх, bg=низ)."""

    def __init__(s):
        s.pt = s.pb = None

    def frame(s, buf, thr=6):
        top, bot = buf[0::2].astype(np.int16), buf[1::2].astype(np.int16)
        if s.pt is None or s.pt.shape != top.shape:
            s.pt, s.pb = np.full_like(top, -99), np.full_like(bot, -99)
            sys.stdout.write('\033[0m\033[2J')
        ch = (np.abs(top - s.pt).max(-1) > thr) | (np.abs(bot - s.pb).max(-1) > thr)
        s.pt[ch], s.pb[ch] = top[ch], bot[ch]
        out = []
        for y in np.where(ch.any(1))[0]:
            xs = np.where(ch[y])[0]
            tl, bl = top[y, xs].tolist(), bot[y, xs].tolist()  # питоновские int — форматирование заметно быстрее
            prev = -9
            for x, t, b in zip(xs.tolist(), tl, bl):
                if x != prev + 1:
                    out.append('\033[%d;%dH' % (y + 1, x + 1))
                out.append('\033[38;2;%d;%d;%d;48;2;%d;%d;%dm▀' % (t[0], t[1], t[2], b[0], b[1], b[2]))
                prev = x
        return ''.join(out)

    def invalidate_row(s, y):
        if s.pt is not None and y < len(s.pt):
            s.pt[y], s.pb[y] = -99, -99


def query_bg(fd):
    try:
        os.write(1, b'\033]11;?\033\\')
        if not select.select([fd], [], [], .3)[0]:
            return FALLBACK_BG
        m = re.search(r'rgb:([0-9a-f]+)/([0-9a-f]+)/([0-9a-f]+)', os.read(fd, 64).decode('latin1'))
        return tuple(int(int(v, 16) / (16 ** len(v) - 1) * 255) for v in m.groups()) if m else FALLBACK_BG
    except Exception:
        return FALLBACK_BG


SHARP_MAX = 6
KEYS = {'n': 'new', '[': 'sharp_dn', ']': 'sharp_up', 'х': 'sharp_dn', 'ъ': 'sharp_up', 'т': 'new', 'p': 'preset', 'з': 'preset', 's': 'season', 'ы': 'season',
        'i': 'random', 'ш': 'random', 'b': 'bd', 'и': 'bd', 'l': 'tl', 'д': 'tl', 'w': 'weather', 'ц': 'weather', 'd': 'tod', 'в': 'tod',
        'e': 'deco', 'у': 'deco', 'f': 'lighter', 'а': 'lighter', 'q': 'quit', 'й': 'quit', '\x1b[A': 'up', '\x1b[B': 'down', '\x1b[C': 'faster', '\x1b[D': 'slower'}


def randomize(sc):
    """Новое дерево со случайными видом, сезоном, погодой и ветром; время суток не трогаем."""
    sc.preset = random.choice(list(PRESETS))
    sc.season = random.choice(SEASON_NAMES)
    sc.wx_name = random.choices(list(WEATHER), weights=(4, 3, 2, 2))[0]
    sc.wind = random.choice((0, .5, 1, 1, 1.5, 2, 3))
    sc.seed = random.randrange(10 ** 6)
    sc.new_tree()


def save_state(sc):
    if sc.tl is not None:   # таймлапс не сохраняем: дерево из него — временное
        return
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, 'w') as f:
            m = sc.mem_snapshot()
            json.dump(dict(preset=sc.preset, seed=getattr(sc, 'seed_next', sc.seed) if sc.gone else sc.seed, gt=0 if sc.gone else sc.gt, spd=sc.spd, rnd=sc.rmode, harv=sc.harv, deco=sc.deco_mode, sharp=sc.sharp,
                           pruned=dict(preset=sc.preset, seed=sc.seed, idx=m[(sc.preset, sc.seed)]) if m else None), f)
    except OSError:
        pass


def load_state():
    try:
        with open(STATE) as f:
            d = json.load(f)
        return d if d.get('preset') in PRESETS else {}
    except (OSError, ValueError):
        return {}



PRESET_RU = {'apple': 'яблоня', 'oak': 'дуб', 'sakura': 'сакура', 'birch': 'берёза', 'acacia': 'акация', 'willow': 'ива', 'pine': 'сосна'}
SEASON_RU = {'spring': 'весна', 'summer': 'лето', 'autumn': 'осень', 'winter': 'зима'}


# нижняя панель: цвета сегментов (текст, фон, жирный)
ACC = (94, 190, 176)
NAV_BG = (20, 24, 30)
PILL = (36, 43, 53)
NAV_STYLE = {'key': (ACC, PILL, True), 'lab': ((128, 140, 154), PILL, False),
             'val': ((238, 242, 246), PILL, True), 'arrow': (ACC, PILL, True),
             'btn': ((214, 222, 230), PILL, False), 'on': (ACC, PILL, True)}


def nav_style(st):
    return st if isinstance(st, tuple) else NAV_STYLE[st]


def rounded(btn):
    """Скруглённые края кнопки половинками блока."""
    return [('▐', ((btn[0][1] and nav_style(btn[0][1])[1]), NAV_BG, False), btn[0][2])] + btn + \
           [('▌', (nav_style(btn[-1][1])[1], NAV_BG, False), btn[-1][2])]


def nav_items(sc):
    """Кнопки нижней панели. Кнопка — список сегментов (текст, стиль, действие); ширина подписей постоянная."""
    def pad(v, opts):
        return v.ljust(max(len(o) for o in opts))

    def step(lab, val, dn, up, mid):
        return [(' ‹', 'arrow', dn), (' %s ' % lab, 'lab', mid), (val + ' ', 'val', mid), ('› ', 'arrow', up)]

    def pick(key, lab, val, opts, act):
        return [(' %s ' % key, 'key', act), ('%s ' % lab, 'lab', act), (pad(val, opts) + ' ', 'val', act)]
    spd = 'пауза' if not SPEEDS[sc.spd] else '×%g' % SPEEDS[sc.spd]
    return [rounded(b) for b in [step('рост', spd.ljust(5), 'slower', 'faster', 'speed0'),
            step('ветер', '%.1f' % sc.wind, 'down', 'up', 'wind0'),
            step('чёткость', ('%d' % sc.sharp if sc.sharp else '—').ljust(2), 'sharp_dn', 'sharp_up', 'sharp0'),
            pick('w', 'погода', WX_NAMES[sc.wx_name], WX_NAMES.values(), 'weather'),
            pick('d', 'время', TOD_NAMES[sc.tod_name], TOD_NAMES.values(), 'tod'),
            pick('s', 'сезон', SEASON_RU[sc.season], SEASON_RU.values(), 'season'),
            pick('p', 'вид', PRESET_RU.get(sc.preset, sc.preset), PRESET_RU.values(), 'preset'),
            pick('b', 'фон', BD_RU[sc.bd_name], BD_RU.values(), 'bd'),
            pick('f', 'зажигалка', 'вкл' if sc.lighter else 'выкл', ('вкл', 'выкл'), 'lighter'),
            pick('e', 'декор', DECO_RU[sc.deco_mode], DECO_RU.values(), 'deco'),
            [(' n ', 'key', 'new'), ('новое ', 'btn', 'new')],
            [(' i ', 'key', 'random'), ('∞ случайно ', 'lab', 'random'), ('вкл ' if sc.rmode else 'выкл', 'on' if sc.rmode else 'val', 'random')],
            [(' l ', 'key', 'tl'), ('таймлапс ', 'lab', 'tl'), ('идёт' if sc.tl is not None else 'выкл', 'on' if sc.tl is not None else 'val', 'tl')],
            [(' q ', 'key', 'quit'), ('выход ', 'btn', 'quit')]]]


def nav_layout(items, W):
    """Сетка кнопок одинаковой ширины: [[(x, текст, стиль, действие)]]. Колонок столько, сколько влезает."""
    widths = [sum(len(t) for t, _, _ in it) for it in items]
    n, wmax = len(items), max(widths)
    cols = max(1, min(n, (W - 1) // (wmax + 1)))
    rows_n = -(-n // cols)
    cols = -(-n // rows_n)                      # ровнее: 8 кнопок в 3 колонки -> 3 строки по 3/3/2
    cw = max(wmax, (W - 2) // cols - 1)
    rows = []
    for r in range(rows_n):
        row, x = [], 1
        for it, w in zip(items[r * cols:(r + 1) * cols], widths[r * cols:(r + 1) * cols]):
            segs = list(it)
            k = max(i for i, sg in enumerate(segs) if sg[1] in ('val', 'btn', 'on'))  # лишнее место — в значение
            segs[k] = (segs[k][0] + ' ' * (cw - w), segs[k][1], segs[k][2])
            for t, st, act in segs:
                row.append((x, t, st, act))
                x += len(t)
            x += 1
        rows.append(row)
    return rows


def nav_draw(rows, H, W):
    out = []
    bg = '\033[48;2;%d;%d;%dm' % NAV_BG
    for r, row in enumerate(rows):
        y = H - len(rows) + r + 1
        out.append('\033[%d;1H\033[0m%s\033[2K' % (y, bg))
        for x, t, st, act in row:
            fg, bgc, bold = nav_style(st)
            out.append('\033[%d;%dH\033[%s38;2;%d;%d;%d;48;2;%d;%d;%dm%s' % ((y, x + 1, '1;' if bold else '22;') + tuple(fg) + tuple(bgc) + (t,)))
        out.append('\033[0m')
    return ''.join(out)


def run_tty(a):
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    names = list(PRESETS)
    try:
        tty.setcbreak(fd)
        bg = query_bg(fd)
        sys.stdout.write('\033[?1049h\033[?25l\033[?1002h\033[?1006h')
        W, H = shutil.get_terminal_size()
        st = {} if a.new or a.seed is not None or a.preset else load_state()
        pr = st.get('pruned') or {}
        mem = {(pr['preset'], pr['seed']): pr['idx']} if pr.get('idx') else {}   # срезы «формой» помнятся между запусками
        sc = Scene(W, H * 2, bg, a.preset or st.get('preset', 'oak'), a.season, a.seed if a.seed is not None else st.get('seed'),
                   a.wind, weather=a.weather, tod=a.tod, mem=mem)  # размер уточняется ниже, под панель навигации
        if st:
            sc.gt, sc.spd = st.get('gt', 0.0), st.get('spd', 3)
            sc.sharp = max(0, min(SHARP_MAX, int(st.get('sharp', 0))))
            sc.harv, sc.deco_mode = st.get('harv', 0), st.get('deco', 'auto') if st.get('deco') in DECO_RU else 'auto'
        if a.sharp is not None:
            sc.sharp = max(0, min(SHARP_MAX, a.sharp))
        sc.rmode = a.random or bool(load_state().get('rnd'))
        rows = nav_layout(nav_items(sc), W)
        rows = rows if (H - len(rows)) * 2 >= 16 else []
        sc = remake(sc, W, (H - len(rows)) * 2, bg)
        if sc.rmode:
            randomize(sc)
        sc.snap_env()
        saved, last = time.time(), time.time()
        scr, bar_key = Screen(), None
        while True:
            now = time.time()
            dt = min(now - last, .1)
            last = now
            w, h = shutil.get_terminal_size()
            rows = nav_layout(nav_items(sc), w)
            if (h - len(rows)) * 2 < 16:
                rows = []  # панель слишком низкая — без кнопок, только дерево
            if (w, h, len(rows)) != (W, H, getattr(sc, 'nrows', len(rows))) or sc.ph != (h - len(rows)) * 2:
                W, H = w, h
                sc = remake(sc, W, (H - len(rows)) * 2, bg)
                sc.snap_env()
                scr, bar_key = Screen(), None
            sc.nrows = len(rows)
            sc.advance(dt)
            if sc.rmode and sc.grown() and not sc.stump:  # бесконечный режим (пока на пне не отросло дерево — стоит): дерево постояло — следующее, всё новое
                sc.hold += dt
                if sc.hold > 2:
                    randomize(sc)
                    save_state(sc)
            if now - saved > 20:
                save_state(sc)
                saved = now
            out = scr.frame(sc.draw())
            key = (tuple(t for r in rows for (_, t, _, _) in r), W, H)
            if key != bar_key:
                out += nav_draw(rows, H, W) if rows else ''
                bar_key = key
            sys.stdout.write('\033[?2026h' + out + '\033[?2026l')
            sys.stdout.flush()
            if select.select([fd], [], [], 1 / a.fps)[0]:
                data = os.read(fd, 4096).decode('utf-8', 'ignore')
                for tok in re.findall(r'\x1b\[<\d+;\d+;\d+[Mm]|\x1b\[[A-D]|.', data, re.S):
                    k = None
                    if tok.startswith('\x1b[<'):
                        b, cx, cy = map(int, tok[3:-1].split(';'))
                        if b & 64 or b & 3 == 2 or b & 3 == 1:
                            continue  # колесо, правая и средняя кнопки
                        if rows and cy > H - len(rows):  # нижняя панель: нажатие по кнопке
                            if tok[-1] == 'M' and not b & 32:
                                r = rows[min(max(cy - (H - len(rows)) - 1, 0), len(rows) - 1)]
                                k = next((act for x0, t, st, act in r if x0 < cx <= x0 + len(t)), None)
                            elif tok[-1] == 'm':
                                sc.release(cx - .5, sc.ph - 1.0)  # отпустили над панелью — закончить линию среза
                            if k is None:
                                continue
                        else:
                            mx, my = cx - .5, cy * 2 - 1.0
                            if tok[-1] == 'm':
                                sc.release(mx, my)
                            elif b & 32 and b & 3 == 3:
                                if sc.lighter:
                                    sc.mouse = (mx, my)  # наведение: огонёк зажигалки идёт за курсором (остальное — ничего)
                            elif b & 32:
                                sc.drag_to(mx, my)      # левая зажата: линия среза
                            else:
                                sc.press(mx, my)
                            continue
                    else:
                        k = KEYS.get(tok)
                    if k == 'quit' or tok == '\x03':
                        return
                    if k == 'new':
                        if sc.rmode:
                            randomize(sc)
                        else:
                            sc.seed = random.randrange(10 ** 6)
                            sc.new_tree()
                        save_state(sc)
                    elif k == 'random':
                        if sc.tl is not None:
                            sc.end_timelapse()
                        sc.rmode = not sc.rmode
                        if sc.rmode:
                            randomize(sc)
                        save_state(sc)
                    elif k == 'bd':
                        bs = list(BD_RU)
                        sc.bd_name = bs[(bs.index(sc.bd_name) + 1) % len(bs)]
                        sc.build_backdrop()
                    elif k == 'lighter':
                        sc.lighter, sc.lit, sc.mouse = not sc.lighter, False, None   # огонёк появится, когда мышь сдвинут над сценой
                    elif k == 'deco':
                        ds = list(DECO_RU)
                        sc.deco_mode = ds[(ds.index(sc.deco_mode) + 1) % len(ds)]
                    elif k == 'tl':
                        if sc.tl is None:
                            sc.start_timelapse()
                        else:
                            sc.end_timelapse()
                    elif k == 'preset':
                        sc.preset = names[(names.index(sc.preset) + 1) % len(names)]
                        sc.new_tree()
                    elif k == 'season':
                        sc.season = SEASON_NAMES[(SEASON_NAMES.index(sc.season) + 1) % 4]
                        sc.restyle()
                    elif k in ('up', 'down'):
                        sc.wind = max(0, min(4, sc.wind + (.5 if k == 'up' else -.5)))
                    elif k == 'wind0':
                        sc.wind = 1.0
                    elif k in ('sharp_up', 'sharp_dn'):
                        sc.sharp = max(0, min(SHARP_MAX, sc.sharp + (1 if k == 'sharp_up' else -1)))
                        save_state(sc)
                    elif k == 'sharp0':
                        sc.sharp = 0 if sc.sharp else 3
                        save_state(sc)
                    elif k in ('faster', 'slower'):
                        sc.spd = max(0, min(len(SPEEDS) - 1, sc.spd + (1 if k == 'faster' else -1)))
                    elif k == 'speed0':
                        sc.spd = 3 if sc.spd != 3 else 0
                    elif k == 'weather':
                        ws = list(WEATHER)
                        sc.wx_name = ws[(ws.index(sc.wx_name) + 1) % len(ws)]
                    elif k == 'tod':
                        ts = list(TOD_NAMES)
                        sc.tod_name = ts[(ts.index(sc.tod_name) + 1) % len(ts)]
    except KeyboardInterrupt:
        pass
    finally:
        try:
            save_state(sc)
        except NameError:
            pass
        sys.stdout.write('\033[0m\033[?1002l\033[?1006l\033[?25h\033[?1049l')
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def remake(old, W, ph, bg):
    """Новая сцена под размер панели с тем же деревом, возрастом, погодой и временем."""
    sc = Scene(W, ph, bg, old.preset, old.season, old.seed, old.wind, weather=old.wx_name, tod=old.tod_name, mem=old.mem_snapshot())
    sc.gt, sc.spd, sc.rmode, sc.clock = old.gt, old.spd, old.rmode, old.clock
    sc.tool, sc.deco_mode, sc.harv, sc.lighter, sc.sharp = old.tool, old.deco_mode, old.harv, old.lighter, old.sharp
    for q in old.saps:   # саженцы переезжают: тот же seed и возраст, место — доля ширины
        sc.add_sap(min(max(q['x'] / old.pw * W, 3), W - 3), q['seed'], max(24, int(q['sh'] / old.ph * ph)), sc.t - (old.t - q['t0']))
    sc.tl, sc.tl_saved = old.tl, old.tl_saved
    if old.bd_name != 'rand':
        sc.bd_name = old.bd_name
        sc.build_backdrop()
    return sc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--preset', choices=list(PRESETS))
    ap.add_argument('--season', default='auto')
    ap.add_argument('--seed', type=int)
    ap.add_argument('--new', action='store_true', help='не брать сохранённое дерево')
    ap.add_argument('--random', action='store_true', help='бесконечный режим: дерево за деревом, вид/сезон/погода/ветер случайные, время суток по часам')
    ap.add_argument('--weather', default='clear', choices=list(WEATHER))
    ap.add_argument('--tod', default='auto', choices=list(TOD_NAMES))
    ap.add_argument('--age', type=float, default=0, help='возраст для --shot/--video, секунд роста после первого')
    ap.add_argument('--wind', type=float, default=1.0)
    ap.add_argument('--sharp', type=int, default=None, help='чёткость 0..6 (по умолчанию из state.json)')
    ap.add_argument('--fps', type=int, default=20)
    ap.add_argument('--burn', type=float, default=-1, help='для --shot/--video: поджечь ствол и ждать столько секунд (для --video — сразу в начале)')
    ap.add_argument('--shot')
    ap.add_argument('--video')
    ap.add_argument('--size', default='100x50')
    ap.add_argument('--scale', type=int, default=8)
    ap.add_argument('--seconds', type=float, default=24)
    ap.add_argument('--bg', default='1e242a')
    a = ap.parse_args()
    if a.season == 'auto':
        a.season = season_now()
    if a.shot or a.video:
        W, H = map(int, a.size.split('x'))
        bg = tuple(int(a.bg[i:i + 2], 16) for i in (0, 2, 4))
        sc = Scene(W, H * 2, bg, a.preset or 'oak', a.season, a.seed if a.seed is not None else 1, a.wind, weather=a.weather, tod=a.tod)
        sc.sharp = a.sharp or 0
        sc.snap_env()
        if a.shot:
            sc.gt = sc.grow_time * 1.12 + a.age
            for _ in range(int(a.fps * 12)):  # прогнать листопад
                sc.advance(1 / a.fps)
            if a.burn >= 0:
                sc.ignite(sc.chain[len(sc.chain) // 4])
                for _ in range(int(a.fps * a.burn)):
                    sc.advance(1 / a.fps)
            save_png(a.shot, sc.draw(), a.scale)
        else:
            p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                                  '-s', '%dx%d' % (W * a.scale, H * 2 * a.scale), '-r', str(a.fps), '-i', '-',
                                  '-pix_fmt', 'yuv420p', '-movflags', '+faststart', a.video], stdin=subprocess.PIPE)
            if a.burn >= 0:
                sc.gt = sc.grow_time * 1.12 + a.age
                sc.ignite(sc.chain[len(sc.chain) // 4])
            for _ in range(int(a.seconds * a.fps)):
                sc.advance(1 / a.fps)
                f = sc.draw()
                p.stdin.write(np.repeat(np.repeat(f, a.scale, 0), a.scale, 1).tobytes())
            p.stdin.close()
            p.wait()
        return
    run_tty(a)


if __name__ == '__main__':
    main()
