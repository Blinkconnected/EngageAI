"""Setting Arabic text in a PDF, so it reads as writing rather than as debris.

ReportLab draws the codepoints it is given, left to right, one glyph each. For
Latin that is the whole job. For Arabic it is not: the script is written right
to left, and every letter takes one of four shapes depending on what it joins
to on each side. Handed raw Arabic, reportlab produces a line of disconnected,
backwards letters — technically the right characters, and unreadable as a word.

So text bound for the page passes through two steps here:

**Shaping.** Each letter is replaced by its contextual form from Arabic
Presentation Forms-B (U+FE70–U+FEFF), chosen from whether the letter before it
joins forwards and the letter after it joins backwards. The bundled DejaVu Sans
carries all 141 of those forms, which is what makes this possible without a
full text-shaping engine.

**Ordering.** The shaped run is reversed, because the renderer will draw it
left to right and Arabic is read right to left.

This is deliberately not a general bidi implementation. It handles what an
invoice actually contains — a company's legal name, an address, a description
— which is a run of Arabic possibly holding Latin words, digits and
punctuation. Mixed paragraphs with nested directional embeddings are the
Unicode Bidirectional Algorithm's problem, and a billing module is the wrong
place to grow one. What it does do, it does correctly, and what it does not
do, it leaves alone: text with no Arabic in it is returned untouched, byte for
byte, so every Latin invoice is completely unaffected.
"""

from __future__ import annotations

#: Letters that join to the *following* letter as well as the preceding one.
#: Everything else in the alphabet joins only backwards, which is why a word
#: containing one breaks into visually separate pieces.
_DUAL: dict[str, tuple[str, str, str, str]] = {
    # base: (isolated, final, initial, medial)
    "ء": ("ﺀ", "ﺀ", "ﺀ", "ﺀ"),  # hamza
    "آ": ("ﺁ", "ﺂ", "ﺁ", "ﺂ"),  # alef madda
    "أ": ("ﺃ", "ﺄ", "ﺃ", "ﺄ"),  # alef hamza above
    "ؤ": ("ﺅ", "ﺆ", "ﺅ", "ﺆ"),  # waw hamza
    "إ": ("ﺇ", "ﺈ", "ﺇ", "ﺈ"),  # alef hamza below
    "ئ": ("ﺉ", "ﺊ", "ﺋ", "ﺌ"),  # yeh hamza
    "ا": ("ﺍ", "ﺎ", "ﺍ", "ﺎ"),  # alef
    "ب": ("ﺏ", "ﺐ", "ﺑ", "ﺒ"),  # beh
    "ة": ("ﺓ", "ﺔ", "ﺓ", "ﺔ"),  # teh marbuta
    "ت": ("ﺕ", "ﺖ", "ﺗ", "ﺘ"),  # teh
    "ث": ("ﺙ", "ﺚ", "ﺛ", "ﺜ"),  # theh
    "ج": ("ﺝ", "ﺞ", "ﺟ", "ﺠ"),  # jeem
    "ح": ("ﺡ", "ﺢ", "ﺣ", "ﺤ"),  # hah
    "خ": ("ﺥ", "ﺦ", "ﺧ", "ﺨ"),  # khah
    "د": ("ﺩ", "ﺪ", "ﺩ", "ﺪ"),  # dal
    "ذ": ("ﺫ", "ﺬ", "ﺫ", "ﺬ"),  # thal
    "ر": ("ﺭ", "ﺮ", "ﺭ", "ﺮ"),  # reh
    "ز": ("ﺯ", "ﺰ", "ﺯ", "ﺰ"),  # zain
    "س": ("ﺱ", "ﺲ", "ﺳ", "ﺴ"),  # seen
    "ش": ("ﺵ", "ﺶ", "ﺷ", "ﺸ"),  # sheen
    "ص": ("ﺹ", "ﺺ", "ﺻ", "ﺼ"),  # sad
    "ض": ("ﺽ", "ﺾ", "ﺿ", "ﻀ"),  # dad
    "ط": ("ﻁ", "ﻂ", "ﻃ", "ﻄ"),  # tah
    "ظ": ("ﻅ", "ﻆ", "ﻇ", "ﻈ"),  # zah
    "ع": ("ﻉ", "ﻊ", "ﻋ", "ﻌ"),  # ain
    "غ": ("ﻍ", "ﻎ", "ﻏ", "ﻐ"),  # ghain
    "ـ": ("ـ", "ـ", "ـ", "ـ"),  # tatweel
    "ف": ("ﻑ", "ﻒ", "ﻓ", "ﻔ"),  # feh
    "ق": ("ﻕ", "ﻖ", "ﻗ", "ﻘ"),  # qaf
    "ك": ("ﻙ", "ﻚ", "ﻛ", "ﻜ"),  # kaf
    "ل": ("ﻝ", "ﻞ", "ﻟ", "ﻠ"),  # lam
    "م": ("ﻡ", "ﻢ", "ﻣ", "ﻤ"),  # meem
    "ن": ("ﻥ", "ﻦ", "ﻧ", "ﻨ"),  # noon
    "ه": ("ﻩ", "ﻪ", "ﻫ", "ﻬ"),  # heh
    "و": ("ﻭ", "ﻮ", "ﻭ", "ﻮ"),  # waw
    "ى": ("ﻯ", "ﻰ", "ﻯ", "ﻰ"),  # alef maksura
    "ي": ("ﻱ", "ﻲ", "ﻳ", "ﻴ"),  # yeh
}

#: Letters that do not join to what follows them. A word carries on after one,
#: but visually detached — which is correct, not a rendering fault.
_RIGHT_JOINING = frozenset("آأؤإاةدذرزوى")

#: Lam followed by an alef is a required ligature in Arabic — writing the two
#: letters side by side is not merely ugly, it is wrong.
_LAM_ALEF: dict[str, tuple[str, str]] = {
    # alef after lam: (isolated ligature, final ligature)
    "آ": ("ﻵ", "ﻶ"),
    "أ": ("ﻷ", "ﻸ"),
    "إ": ("ﻹ", "ﻺ"),
    "ا": ("ﻻ", "ﻼ"),
}

_LAM = "ل"

#: Marks that sit on a letter rather than beside it. They take no shape of
#: their own and must not break a join between the letters around them.
_TRANSPARENT = frozenset("ًٌٍَُِّْٰٕٓٔ")


def has_arabic(text: str) -> bool:
    """Whether any of this is Arabic script at all.

    The guard in front of everything below: Latin text must come back
    identical, and the cheapest way to guarantee that is not to touch it.
    """
    return any(0x0600 <= ord(ch) <= 0x06FF or 0xFB50 <= ord(ch) <= 0xFEFF for ch in text)


def _joins_forward(ch: str) -> bool:
    return ch in _DUAL and ch not in _RIGHT_JOINING


def _joins_backward(ch: str) -> bool:
    return ch in _DUAL


def _neighbour(chars: list[str], index: int, step: int) -> str | None:
    """The next letter that actually takes part in joining.

    Vowel marks are skipped rather than treated as breaks: a fatha between
    two letters does not stop them joining, and treating it as a boundary
    would split every vocalised word into pieces.
    """
    position = index + step
    while 0 <= position < len(chars):
        if chars[position] not in _TRANSPARENT:
            return chars[position]
        position += step
    return None


def shape(text: str) -> str:
    """Arabic, in the forms it is actually written in, ordered for drawing.

    Returns ``text`` unchanged when there is no Arabic in it — so a Latin
    invoice is byte-identical to one rendered before this module existed.
    """
    if not has_arabic(text):
        return text

    chars = list(text)
    shaped: list[str] = []
    index = 0
    while index < len(chars):
        current = chars[index]

        # Lam-alef first: the pair becomes one glyph, so it has to be
        # recognised before either letter is shaped on its own.
        if current == _LAM:
            following = _neighbour(chars, index, 1)
            if following in _LAM_ALEF:
                previous = _neighbour(chars, index, -1)
                joined_before = previous is not None and _joins_forward(previous)
                isolated, final = _LAM_ALEF[following]
                shaped.append(final if joined_before else isolated)
                # Skip the alef, and any marks between the two letters.
                index += 1
                while index < len(chars) and chars[index] in _TRANSPARENT:
                    index += 1
                index += 1
                continue

        if current not in _DUAL:
            shaped.append(current)
            index += 1
            continue

        previous = _neighbour(chars, index, -1)
        following = _neighbour(chars, index, 1)
        joined_before = previous is not None and _joins_forward(previous)
        joined_after = following is not None and _joins_backward(following)

        isolated, final, initial, medial = _DUAL[current]
        if joined_before and joined_after and _joins_forward(current):
            shaped.append(medial)
        elif joined_before:
            shaped.append(final)
        elif joined_after and _joins_forward(current):
            shaped.append(initial)
        else:
            shaped.append(isolated)
        index += 1

    return _to_visual_order("".join(shaped))


#: Characters whose shape mirrors when the line runs the other way. A closing
#: parenthesis at the end of an Arabic phrase is drawn as an opening one.
_MIRRORED = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<"}


def _to_visual_order(text: str) -> str:
    """Right-to-left, with Latin and numbers left alone inside it.

    The renderer draws left to right, so the Arabic is reversed here. Runs of
    Latin letters and digits are reversed *back* afterwards: an Arabic name
    containing "IT" or a year must not come out as "TI" or "6202". This is
    the practical core of bidi for the one case an invoice contains — a line
    that is mostly Arabic with occasional Latin islands.
    """
    reversed_text = "".join(_MIRRORED.get(ch, ch) for ch in reversed(text))

    # Put each Latin/digit island back the way round it was written.
    out: list[str] = []
    island: list[str] = []
    for ch in reversed_text:
        if ch.isascii() and (ch.isalnum() or ch in "@._-/:"):
            island.append(ch)
            continue
        if island:
            out.extend(reversed(island))
            island = []
        out.append(ch)
    if island:
        out.extend(reversed(island))
    return "".join(out)


__all__ = ["has_arabic", "shape"]
