"""Built-in presets (cannot be deleted). The reasoning behind the values is in `why` and in docs/agents/status-paket-f.md."""
from app.convert_schema import clean_v2

STD = "aq-mode=3:no-sao=1"        # previous default: aq-mode 3 protects dark scenes (less blocking), SAO off keeps fine detail
NVENC_HQ = "preset=p7:tune=hq:profile=main10:multipass=fullres:rc-lookahead=32:spatial-aq=1:temporal-aq=1:bf=4:b_ref_mode=middle"


def _p(pid, name, desc, why, video=None, quality=None, picture=None, sound=None, kind=""):
    cfg = clean_v2({"v": 2, "convert": True, "origin": pid,
                    "video": {"codec": "x265", "bits": 10, "speed": "slow", "tune": "none", "extra": STD, **(video or {})},
                    "quality": {"mode": "crf", "crf": 20, **(quality or {})}, "picture": picture or {}, "sound": sound or {}})
    return {"id": pid, "name": name, "desc": desc, "why": why, "builtin": True, "kind": kind, "cfg": cfg}


BUILTIN = [
    _p("dvd", "DVD optimal", "For DVD rips (SD): detects interlacing itself, denoises lightly, audio stays.",
       "SD sources: HandBrake recommends RF 18–22. RF 19, because MPEG-2 noise otherwise costs a lot of bits; light hqdn3d (2:1:2:3) and automatic "
       "interlace detection (idet → bwdif or IVTC), because many DVDs are interlaced or telecined.",
       quality={"crf": 19}, picture={"deint": "auto", "denoise": "light"}, kind="dvd"),
    _p("bluray", "Blu-ray optimal", "The default for 1080p discs: looks like the original, needs about a third of the space.",
       "1080p: HandBrake RF 20–24; RF 20 with slow and aq-mode=3 is the previous default (RF 21 before).", quality={"crf": 20}, kind="bluray"),
    _p("animation", "Blu-ray animation", "Cartoons and anime: flat areas need fewer bits.",
       "x265 --tune animation sets psy-rd 0.4, aq-strength 0.4, deblock 1:1 and more B-frames; flat color areas tolerate a higher RF (22). "
       "No custom aq parameters, so that the tune takes effect.", video={"tune": "animation", "extra": ""}, quality={"crf": 22}),
    _p("grain", "Film with heavy grain", "Old film material: the grain is kept, the file gets larger.",
       "x265 --tune grain sets aq-mode 0, cutree 0, psy-rd 4.0, psy-rdoq 10.0, sao 0 – grain is not smoothed away. RF 19, because grain costs bits. "
       "No aq-mode=3 in extra (it would override the tune).", video={"tune": "grain", "extra": ""}, quality={"crf": 19}),
    _p("uhd", "UHD / keep HDR", "4K discs: HDR10 metadata is passed through, 10 bit is mandatory.",
       "2160p: HandBrake RF 22–28; RF 22 with medium (slow would be very slow for 4K). HDR10 (mastering display, MaxCLL) and BT.2020/PQ tagging "
       "are taken from the source (hdr10-opt, repeat-headers). Dolby Vision is lost, the HDR10 base stays.",
       video={"speed": "medium", "extra": "aq-mode=3"}, quality={"crf": 22}, kind="uhd"),
    _p("small", "Small & fast", "For on the go: at most 720p, fast, stereo audio (AAC).",
       "720p, RF 26, faster: much smaller and about 4× faster than slow; stereo AAC at 160 kb/s plays everywhere.",
       video={"speed": "faster", "extra": ""}, quality={"crf": 26}, picture={"scale": "720", "deint": "auto"}, sound={"mode": "aac", "channels": "stereo"}),
    _p("bluray-nvenc", "Blu-ray NVIDIA (NVENC)", "For machines with an NVIDIA card: HEVC 10 bit on the graphics card, much faster, audio and subtitles stay.",
       "hevc_nvenc main10 (less banding, even with an 8-bit source), p7 + tune hq costs hardly any time on the GPU. VBR with CQ 22 (20 = very good, 24 = smaller) "
       "for constant quality instead of a fixed bitrate; multipass fullres, lookahead 32, spatial + temporal AQ against blocking in dark and flat scenes; "
       "4 B-frames with b_ref_mode middle (Turing/Ampere and later). Audio and subtitles are copied.",
       video={"codec": "hw", "hw": "hevc_nvenc", "extra": NVENC_HQ}, quality={"crf": 22}, kind="bluray"),
    _p("dvd-x265", "DVD gentle (x265)", "For DVD rips: RF 19, original resolution, black bars removed, audio and subtitles stay.",
       "DVDs are already heavily compressed, so not too aggressive: x265 10 bit slow with RF 19 (range 18–20). The resolution stays (no upscaling), "
       "the anamorphic aspect ratio is carried over, black borders are cropped automatically. AC3 and VobSub fit into MKV unchanged. "
       "Interlacing is detected automatically (many DVDs are interlaced).",
       quality={"crf": 19}, picture={"crop": "auto", "deint": "auto"}, kind="dvd"),
]
BUILTIN_IDS = {p["id"] for p in BUILTIN}
DEFAULT_FOR = {"bluray": "bluray", "dvd": "dvd", "uhd": "uhd"}
NVIDIA_DEFAULT_FOR = {"bluray": "bluray-nvenc", "dvd": "dvd-x265"}      # preselected if this machine can do hevc_nvenc with 10 bit
