"""Mitgelieferte Presets (nicht löschbar). Die Begründung der Werte steht in `why` und in docs/agenten/status-paket-f.md."""
from app.convert_schema import clean_v2

STD = "aq-mode=3:no-sao=1"        # bisheriger Standard: aq-mode 3 schont dunkle Szenen (weniger Blockbildung), SAO aus erhält feine Details
NVENC_HQ = "preset=p7:tune=hq:profile=main10:multipass=fullres:rc-lookahead=32:spatial-aq=1:temporal-aq=1:bf=4:b_ref_mode=middle"


def _p(pid, name, desc, why, video=None, quality=None, picture=None, sound=None, kind=""):
    cfg = clean_v2({"v": 2, "convert": True, "origin": pid,
                    "video": {"codec": "x265", "bits": 10, "speed": "slow", "tune": "none", "extra": STD, **(video or {})},
                    "quality": {"mode": "crf", "crf": 20, **(quality or {})}, "picture": picture or {}, "sound": sound or {}})
    return {"id": pid, "name": name, "desc": desc, "why": why, "builtin": True, "kind": kind, "cfg": cfg}


BUILTIN = [
    _p("dvd", "DVD optimal", "Für DVD-Rips (SD): erkennt Zeilensprung selbst, entrauscht leicht, Ton bleibt.",
       "SD-Quellen: HandBrake empfiehlt RF 18–22. RF 19, weil MPEG-2-Rauschen sonst viele Bits kostet; hqdn3d leicht (2:1:2:3) und automatische "
       "Zeilensprung-Erkennung (idet → bwdif bzw. IVTC), denn viele DVDs sind interlaced oder telecined.",
       quality={"crf": 19}, picture={"deint": "auto", "denoise": "light"}, kind="dvd"),
    _p("bluray", "Blu-ray optimal", "Der Standard für 1080p-Discs: sieht aus wie das Original, braucht etwa ein Drittel.",
       "1080p: HandBrake RF 20–24; RF 20 mit slow und aq-mode=3 ist der bisherige Standard (vorher RF 21).", quality={"crf": 20}, kind="bluray"),
    _p("animation", "Blu-ray Animation", "Zeichentrick und Anime: glatte Flächen brauchen weniger Bits.",
       "x265 --tune animation setzt psy-rd 0.4, aq-strength 0.4, deblock 1:1 und mehr B-Frames; flache Farbflächen vertragen höheres RF (22). "
       "Keine eigenen aq-Parameter, damit der Tune wirkt.", video={"tune": "animation", "extra": ""}, quality={"crf": 22}),
    _p("grain", "Film mit starkem Korn", "Altes Filmmaterial: Korn bleibt erhalten, die Datei wird größer.",
       "x265 --tune grain setzt aq-mode 0, cutree 0, psy-rd 4.0, psy-rdoq 10.0, sao 0 – Korn wird nicht weggeglättet. RF 19, weil Korn Bits kostet. "
       "Kein aq-mode=3 in extra (würde den Tune überschreiben).", video={"tune": "grain", "extra": ""}, quality={"crf": 19}),
    _p("uhd", "UHD / HDR erhalten", "4K-Discs: HDR10-Angaben werden durchgereicht, 10 Bit ist Pflicht.",
       "2160p: HandBrake RF 22–28; RF 22 mit medium (slow wäre bei 4K sehr langsam). HDR10 (Mastering-Display, MaxCLL) und BT.2020/PQ-Kennzeichnung "
       "werden aus der Quelle übernommen (hdr10-opt, repeat-headers). Dolby Vision geht verloren, die HDR10-Basis bleibt.",
       video={"speed": "medium", "extra": "aq-mode=3"}, quality={"crf": 22}, kind="uhd"),
    _p("small", "Klein & schnell", "Für unterwegs: höchstens 720p, schnell, Stereo-Ton (AAC).",
       "720p, RF 26, faster: deutlich kleiner und etwa 4× schneller als slow; Stereo-AAC 160 kb/s ist überall abspielbar.",
       video={"speed": "faster", "extra": ""}, quality={"crf": 26}, picture={"scale": "720", "deint": "auto"}, sound={"mode": "aac", "channels": "stereo"}),
    _p("bluray-nvenc", "Blu-ray NVIDIA (NVENC)", "Für Rechner mit NVIDIA-Karte: HEVC 10 Bit auf der Grafikkarte, viel schneller, Ton und Untertitel bleiben.",
       "hevc_nvenc main10 (weniger Banding, auch bei 8-Bit-Quelle), p7 + tune hq kostet auf der GPU kaum Zeit. VBR mit CQ 22 (20 = sehr gut, 24 = kleiner) "
       "für gleichbleibende Qualität statt fester Bitrate; multipass fullres, Lookahead 32, AQ räumlich + zeitlich gegen Blöcke in dunklen und flachen Szenen; "
       "4 B-Frames mit b_ref_mode middle (ab Turing/Ampere). Ton und Untertitel werden kopiert.",
       video={"codec": "hw", "hw": "hevc_nvenc", "extra": NVENC_HQ}, quality={"crf": 22}, kind="bluray"),
    _p("dvd-x265", "DVD schonend (x265)", "Für DVD-Rips: RF 19, Originalauflösung, schwarze Balken weg, Ton und Untertitel bleiben.",
       "DVDs sind schon stark komprimiert, deshalb nicht zu aggressiv: x265 10 Bit slow mit RF 19 (Bereich 18–20). Auflösung bleibt (kein Hochskalieren), "
       "anamorphes Seitenverhältnis wird mitgenommen, schwarze Ränder werden automatisch weggeschnitten. AC3 und VobSub passen unverändert in MKV. "
       "Zeilensprung wird automatisch erkannt (viele DVDs sind interlaced).",
       quality={"crf": 19}, picture={"crop": "auto", "deint": "auto"}, kind="dvd"),
]
BUILTIN_IDS = {p["id"] for p in BUILTIN}
DEFAULT_FOR = {"bluray": "bluray", "dvd": "dvd", "uhd": "uhd"}
NVIDIA_DEFAULT_FOR = {"bluray": "bluray-nvenc", "dvd": "dvd-x265"}      # vorausgewählt, wenn dieser Rechner hevc_nvenc mit 10 Bit kann
