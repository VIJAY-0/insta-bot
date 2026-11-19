"""Choosing the caption for a reel: the sender's text, else the original post's caption,
else a random GTA-style one. No credit line for the original creator."""

import random

CAPTION_LIMIT = 2200  # Instagram's caption limit, in characters

GTA_CAPTIONS = [
    "Wasted. 💀 #GTA",
    "Mission passed! Respect +. ✅ #GTA",
    "Five stars and still not slowing down. ⭐⭐⭐⭐⭐ #GTA",
    "Just another day in Los Santos. 🌴 #GTA",
    "Welcome to Vice City. 🌆 #GTA",
    "This is why you never skip the cutscene. 🎬 #GTA",
    "Cops on my tail, music up loud. 🚓🔊 #GTA",
    "Stole a car, found a new personality. 🚗 #GTA",
    "All we had to do was follow the damn train, CJ. 🚂 #GTA",
    "Wanted level: legendary. 🔥 #GTA",
    "Los Santos never sleeps. 🌙 #GTA",
    "Physics said no. I said watch this. 🏍️ #GTA",
    "GTA logic hits different. 😂 #GTA",
    "Pulling off the heist of the century. 💰 #GTA",
    "Roll the dice, take the score. 🎲 #GTA",
]


def pick_caption(user_text: str, original_caption: str | None, rng: random.Random = random) -> str:
    """The sender's text if any, else the original post's caption, else a random GTA caption."""
    for text in (user_text, original_caption or ""):
        text = text.strip()
        if text:
            return text[:CAPTION_LIMIT]
    return rng.choice(GTA_CAPTIONS)
