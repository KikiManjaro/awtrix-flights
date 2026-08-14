#!/usr/bin/env python3
"""Capture l'écran d'un AWTRIX 3 en GIF animé (sans capture native).

Le firmware AWTRIX 3 n'expose pas d'endpoint de capture (0.98 testé) :
l'API `GET /api/screen` renvoie en revanche le rendu LED brut (256 entiers,
matrice 32×8) avec les vraies couleurs RGB888 encodées en entier
((R<<16)|(G<<8)|B). Ce script interroge cet endpoint à intervalle régulier
et assemble un GIF animé, agrandi pour être lisible.

Usage :
    python3 awtrix_capture.py [--host 192.168.1.27] [--seconds 15] \
        [--fps 2] [--scale 10] [--out screen.gif]

Dépendances : Pillow (uniquement pour cet outil, PAS le runtime du service).
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

from PIL import Image

WIDTH, HEIGHT = 32, 8


def fetch_screen(host: str, port: int = 80) -> list[int]:
    """Interroge /api/screen et retourne les 256 valeurs LED."""
    url = f"http://{host}:{port}/api/screen"
    with urllib.request.urlopen(url, timeout=3) as resp:
        data = json.load(resp)
    if len(data) != WIDTH * HEIGHT:
        raise ValueError(f"réponse inattendue : {len(data)} valeurs (attendu {WIDTH * HEIGHT})")
    return data


def led_frame(host: str, port: int, scale: int) -> Image.Image:
    """Frame PIL 32x8 (agrandie) depuis l'écran réel."""
    values = fetch_screen(host, port)
    img = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = img.load()
    for i, v in enumerate(values):
        x, y = i % WIDTH, i // WIDTH
        r = (v >> 16) & 0xFF
        g = (v >> 8) & 0xFF
        b = v & 0xFF
        pixels[x, y] = (r, g, b)
    return img.resize((WIDTH * scale, HEIGHT * scale), Image.NEAREST)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.1.27", help="IP de l'AWTRIX")
    parser.add_argument("--port", type=int, default=80, help="port API (défaut 80)")
    parser.add_argument("--seconds", type=float, default=15.0, help="durée de capture")
    parser.add_argument("--fps", type=float, default=2.0, help="images par seconde")
    parser.add_argument("--scale", type=int, default=10, help="agrandissement (32x8 -> 320x80)")
    parser.add_argument("--out", default="awtrix.gif", help="fichier GIF de sortie")
    args = parser.parse_args()

    interval = 1.0 / args.fps
    n_frames = max(1, int(args.seconds * args.fps))
    frames: list[Image.Image] = []
    print(
        f"Capture {args.host}:{args.port} — {n_frames} frames à {args.fps} fps "
        f"({args.seconds}s) -> {args.out}"
    )
    for i in range(n_frames):
        try:
            frame = led_frame(args.host, args.port, args.scale)
            frames.append(frame)
            print(f"  frame {i + 1}/{n_frames} OK")
        except Exception as exc:  # noqa: BLE001 - capture best effort
            print(f"  frame {i + 1}/{n_frames} : échec ({exc}), ignorée")
        if i < n_frames - 1:
            time.sleep(interval)

    if not frames:
        print("ERREUR : aucune frame capturée", file=__import__("sys").stderr)
        return 1

    frames[0].save(
        args.out,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / args.fps),
        loop=0,
    )
    print(f"GIF écrit : {args.out} ({len(frames)} frames)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
