#!/usr/bin/env python3
"""
builder_core.py — shared engine for the GBA Compilation Builder
===============================================================

Contains the builder registry, validation and build-command assembly for the
Python 3 builder scripts from:
  https://github.com/patters-match/gba-emu-compilation-builders

This module is used in TWO places:
  * by server.py, running as a normal Python process (subprocess execution)
  * by index.html, loaded into Pyodide in the browser (runpy execution)

Everything file-related is configurable via REPO_DIR / JOBS_DIR so both hosts
can point it at their own filesystem (real disk, or the Pyodide virtual FS).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import unicodedata
import zipfile

# --------------------------------------------------------------------------
# Configurable paths — hosts may override these before use
# --------------------------------------------------------------------------

REPO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "gba-emu-compilation-builders")
JOBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs")

BUILD_TIMEOUT = 900          # seconds per build (subprocess mode only)
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024   # 4 GB per file

EZ4_RAW = "https://raw.githubusercontent.com/patters-match/gba-ezflash-iv-emulators/main"
EZ4_PAGE = "https://github.com/patters-match/gba-ezflash-iv-emulators"

# HVCA mapper files (hvca140/bin/mapr/*.bin in the gba-ezflash-iv-emulators repo)
HVCA_MAPR_FILES = [
    "m000.bin", "m001.bin", "m001_so.bin", "m001_su.bin", "m001_sv.bin",
    "m002.bin", "m002_un1.bin", "m003.bin", "m004.bin", "m004_tks.bin",
    "m004_tr1.bin", "m007.bin", "m009_po.bin", "m010_fw.bin", "m016.bin",
    "m016_01.bin", "m016_02.bin", "m016_fj2.bin", "m018.bin", "m018_snd.bin",
    "m032.bin", "m033.bin", "m033_irq.bin", "m034.bin", "m065.bin", "m066.bin",
    "m067.bin", "m068.bin", "m069.bin", "m069_dsp.bin", "m070_01.bin",
    "m070_hv.bin", "m072.bin", "m072_snd.bin", "m077.bin", "m078_01.bin",
    "m078_vh.bin", "m080_01.bin", "m080_vh.bin", "m082.bin", "m086.bin",
    "m086_snd.bin", "m087.bin", "m089.bin", "m092.bin", "m092_snd.bin",
    "m093.bin", "m097.bin", "m113.bin", "m180.bin", "m184.bin", "m185.bin",
    "mfds.bin", "mn108.bin", "mn109.bin", "mn118.bin", "mn118_a0d6.bin",
    "mn118_a1d5.bin", "mn163.bin", "mn163_dsp.bin", "mnina001.bin", "mnsf.bin",
    "mvrc1.bin", "mvrc2_a0a1.bin", "mvrc2_a1a0.bin", "mvrc3.bin", "mvrc4_a0a1.bin",
    "mvrc4_a2a1.bin", "mvrc4_a2a3.bin", "mvrc4_a3a2.bin", "mvrc4_a7a6.bin",
    "mvrc6_a0a1.bin", "mvrc6_a1a0.bin",
]

# --------------------------------------------------------------------------
# Builder registry — single source of truth for the UI and the build command
# --------------------------------------------------------------------------
#
# emu.fetch        -> URL of a recommended emulator binary (raw file)
# emu.fetch_folder -> spec for folder-style downloads (HVCA needs a 'bin' folder)
# extras           -> optional/required side files, each with the script flag
# options          -> simple on/off switches mapped to script flags

BUILDERS = [
    {
        "id": "pocketnes",
        "name": "PocketNES",
        "system": "Nintendo Entertainment System (NES)",
        "emoji": "\U0001f3ae",  # 🎮
        "tagline": "Play NES games on your Game Boy Advance",
        "description": "PocketNES is the classic NES emulator for GBA. "
                       "You can pack many games into one tidy ROM and pick them from a menu.",
        "script": "pocketnes_compile.py",
        "roms": {"label": "NES game ROMs", "exts": [".nes"],
                 "hint": "Add one or more .nes game files. They appear in the menu in the order you add them."},
        "emu": {"label": "PocketNES emulator", "filename": "pocketnes.gba",
                "fetch": EZ4_RAW + "/pocketnes2020/pocketnes.gba",
                "hint": "This is the program that runs the games on your GBA. "
                        "The recommended download is the exit-patched build (works on EZ-Flash IV / 3in1 / Omega "
                        "and plays fine on everything else)."},
        "extras": [
            {"role": "splash", "flag": "-s", "label": "Splash screen (optional)",
             "exts": [".raw"],
             "hint": "A 76800-byte raw 240x160 15-bit image shown when the ROM boots."},
        ],
        "options": [
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names shown in the menu."},
            {"flag": "-m", "label": "Mark small games with *", "help": "Marks ROMs under 192KB as suitable for link-cable transfer."},
            {"flag": "-dbn", "label": "Use titles from the game database", "help": "Uses nicer official game titles where the built-in database has a match."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "pocketnes-compilation.gba",
    },
    {
        "id": "goomba",
        "name": "Goomba / Jagoomba Color",
        "system": "Game Boy & Game Boy Color",
        "emoji": "\U0001f468\u200d\U0001f4bb",  # 👨‍💻
        "tagline": "Play Game Boy and Game Boy Color games on GBA",
        "description": "Goomba runs Game Boy games on GBA. The recommended emulator build is Jagoomba Color, "
                       "an enhanced Goomba Color fork with the best compatibility.",
        "script": "goomba_compile.py",
        "roms": {"label": "Game Boy ROMs", "exts": [".gb", ".gbc"],
                 "hint": "Add .gb (Game Boy) and/or .gbc (Game Boy Color) game files."},
        "emu": {"label": "Goomba / Jagoomba emulator", "filename": "jagoombacolor.gba",
                "fetch": EZ4_RAW + "/jagoomba05/jagoombacolor.gba",
                "hint": "You can use original Goomba, Goomba Color, or Jagoomba Color binaries here."},
        "extras": [
            {"role": "splash", "flag": "-s", "label": "Splash screen (optional)",
             "exts": [".raw"],
             "hint": "A 76800-byte raw 240x160 15-bit image shown when the ROM boots."},
        ],
        "options": [
            {"flag": "-f", "label": "Use file names as game titles", "help": "Shows the ROM file name in the menu instead of the title stored inside the game."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "goomba-compilation.gba",
    },
    {
        "id": "snesadvance",
        "name": "SNESAdvance",
        "system": "Super Nintendo (SNES)",
        "emoji": "\U0001f3ae",
        "tagline": "Play SNES games on your Game Boy Advance",
        "description": "SNESAdvance squeezes SNES games onto GBA hardware. Compatibility varies per game — "
                       "the built-in SuperDAT database applies the right settings and patches automatically.",
        "script": "snesadvance_compile.py",
        "roms": {"label": "SNES game ROMs", "exts": [".sfc", ".smc"],
                 "hint": "Add .sfc or .smc game files (headered or headerless both work)."},
        "emu": {"label": "SNESAdvance emulator", "filename": "SNESAdvance.bin",
                "fetch": EZ4_RAW + "/snesadvance01f/SNESAdvance.bin",
                "hint": "Note the file is called SNESAdvance.bin (not .gba) — that's normal."},
        "extras": [],
        "options": [
            {"flag": "-dbn", "label": "Use titles from the game database", "help": "Uses nicer official game titles where the SuperDAT database has a match."},
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names shown in the menu."},
            {"flag": "-strip", "label": "Export header-stripped ROMs", "help": "Also writes out cleaned .sfc copies of headered games."},
            {"flag": "-v", "label": "Verbose log", "help": "Shows which patches were applied to each game."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "snesadv-compilation.gba",
    },
    {
        "id": "snezziboy",
        "name": "Snezziboy",
        "system": "Super Nintendo (SNES)",
        "emoji": "\U0001f3ae",
        "tagline": "SNES emulation with excellent speed — one game per ROM",
        "description": "Snezziboy is another SNES emulator for GBA, with great speed. "
                       "Each game gets its own .gba file (each one bundles its own emulator).",
        "script": "snezziboy_compile.py",
        "roms": {"label": "SNES game ROMs", "exts": [".sfc", ".smc"],
                 "hint": "Add .sfc or .smc game files. You will get one .gba per game."},
        "emu": {"label": "Snezziboy emulator", "filename": "snezzi.gba",
                "fetch": EZ4_RAW + "/snezziboy026/snezzi.gba",
                "hint": "One emulator instance is bundled into each game's .gba automatically."},
        "extras": [],
        "options": [
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names."},
            {"flag": "-strip", "label": "Export header-stripped ROMs", "help": "Also writes out cleaned .sfc copies of headered games."},
            {"flag": "-v", "label": "Verbose log", "help": "Mimics the output of the original snezzi.exe build tool."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "",  # defaults to each game's own name
    },
    {
        "id": "pceadvance",
        "name": "PCEAdvance",
        "system": "PC Engine / Super CD-ROM\u00b2",
        "emoji": "\U0001f4bf",  # 💿
        "tagline": "Play PC Engine games (cartridge and CD) on GBA",
        "description": "PCEAdvance runs PC Engine / TurboGrafx-16 games. It even supports CD-ROM\u00b2 games "
                       "(one CD game per compilation).",
        "script": "pceadvance_compile.py",
        "roms": {"label": "PC Engine ROMs", "exts": [".pce", ".iso"],
                 "hint": "Add .pce cartridge games and/or one .iso CD-ROM image. Only one CD game per compilation."},
        "emu": {"label": "PCEAdvance emulator", "filename": "pceadvance.gba",
                "fetch": EZ4_RAW + "/pceadvance75/pceadvance.gba",
                "hint": "The recommended build is exit-patched for EZ-Flash flashcarts."},
        "extras": [
            {"role": "cdrombios", "flag": "-b", "label": "CD-ROM BIOS (needed for .iso games)",
             "exts": [".bin", ".rom"],
             "hint": "The PC Engine CD-ROM System BIOS. Only needed when adding CD-ROM games."},
            {"role": "tcd", "flag": "-t", "label": "CD track list .tcd (optional)",
             "exts": [".tcd"],
             "hint": "Track index file for CD games with multiple data tracks. Defaults to <iso name>.tcd."},
            {"role": "splash", "flag": "-s", "label": "Splash screen (optional)",
             "exts": [".raw"],
             "hint": "A 76800-byte raw 240x160 15-bit image shown when the ROM boots."},
        ],
        "options": [
            {"flag": "-trim", "label": "Trim to fit 16MB PSRAM", "help": "Needed for some Super CD-ROM\u00b2 titles on EZ-Flash devices."},
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "pceadv-compilation.gba",
    },
    {
        "id": "smsadvance",
        "name": "SMSAdvance",
        "system": "Sega Master System / Game Gear / SG-1000",
        "emoji": "\U0001f3ae",
        "tagline": "Play Sega Master System and Game Gear games on GBA",
        "description": "SMSAdvance handles Master System, Game Gear and SG-1000 games and auto-detects "
                       "which system each ROM is for.",
        "script": "smsadvance_compile.py",
        "roms": {"label": "SMS / GG / SG ROMs", "exts": [".sms", ".gg", ".sg"],
                 "hint": "Add .sms (Master System), .gg (Game Gear) or .sg (SG-1000) game files."},
        "emu": {"label": "SMSAdvance emulator", "filename": "smsadvance.gba",
                "fetch": EZ4_RAW + "/smsadvance25/smsadvance.gba",
                "hint": "The recommended build is exit-patched for EZ-Flash flashcarts."},
        "extras": [
            {"role": "bios", "flag": "-b", "label": "System BIOS ROMs (optional)",
             "exts": [".bin", ".rom", ".sms", ".gg"],
             "multiple": True,
             "hint": "Optional Sega BIOS images. You can add both a Master System and a Game Gear BIOS."},
            {"role": "splash", "flag": "-s", "label": "Splash screen (optional)",
             "exts": [".raw"],
             "hint": "A 76800-byte raw 240x160 15-bit image shown when the ROM boots."},
        ],
        "options": [
            {"flag": "-m", "label": "Mark small games with *", "help": "Marks small ROMs as suitable for link-cable transfer."},
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names."},
            {"flag": "-bb", "label": "Add '-- Empty --' BIOS entry", "help": "Boots to the BIOS only. For BIOS-integrated games; set System to Master System in the emulator options."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "smsadv-compilation.gba",
    },
    {
        "id": "hvca",
        "name": "HVCA",
        "system": "NES / Famicom Disk System",
        "emoji": "\U0001f3ae",
        "tagline": "NES and Famicom Disk System games on GBA",
        "description": "HVCA emulates the NES and the Famicom Disk System. It needs its emulator files as a "
                       "small 'bin' folder — we can download the whole set for you.",
        "script": "hvca_compile.py",
        "roms": {"label": "NES / FDS game files", "exts": [".nes", ".fds", ".nsf", ".cfg"],
                 "hint": "Add .nes and/or .fds games (plus optional .nsf music and .cfg config files)."},
        "emu": {"label": "HVCA emulator files (bin folder)", "filename": "hvca-bin",
                "fetch_folder": {
                    "raw": EZ4_RAW + "/hvca140/bin",
                    "files": ["base.bin", "font_a.raw", "font_k.raw"],
                    "subdir": "mapr",
                    "subdir_files": HVCA_MAPR_FILES,
                },
                "zip_ok": True,
                "hint": "HVCA needs a folder of emulator files (base.bin, fonts and mapper files). "
                        "We can download them for you, or you can upload the folder as a .zip file."},
        "extras": [
            {"role": "bios", "flag": "-b", "label": "FDS BIOS - disksys.rom (for .fds games)",
             "exts": [".rom", ".bin"],
             "hint": "The Famicom Disk System BIOS (disksys.rom, 8KB). Only needed for .fds games."},
            {"role": "exitsub", "flag": "-x", "label": "Exit-to-menu code (optional)",
             "exts": [".sub"],
             "hint": "A .sub file with flashcart-specific exit code. A ready-made one for EZ-Flash IV / 3in1 / Omega "
                     "is included with the builder — tick the option below to use it."},
            {"role": "palette", "flag": "-p", "label": "Palette file (optional)",
             "exts": [".pal"],
             "hint": "Optional custom palette."},
        ],
        "options": [
            {"flag": "hvca-exit", "label": "Use bundled EZ-Flash exit code", "help": "Adds the included flash_ez4_ezo.sub so L+R in the menu exits back to your flashcart (EZ-Flash IV / 3in1 / Omega)."},
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names."},
            {"flag": "-v", "label": "Verbose log", "help": "Detailed output like the original hvcamkfs.exe tool."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "hvca-compilation.gba",
    },
    {
        "id": "cologne",
        "name": "Cologne",
        "system": "ColecoVision",
        "emoji": "\U0001f3ae",
        "tagline": "Play ColecoVision games on your Game Boy Advance",
        "description": "Cologne brings ColecoVision classics to GBA. It needs the ColecoVision BIOS to run games.",
        "script": "cologne_compile.py",
        "roms": {"label": "ColecoVision ROMs", "exts": [".col", ".rom"],
                 "hint": "Add .col or .rom ColecoVision game files."},
        "emu": {"label": "Cologne emulator", "filename": "cologne.gba",
                "fetch": EZ4_RAW + "/cologne08/cologne.gba",
                "hint": "The recommended build is exit-patched for EZ-Flash flashcarts."},
        "extras": [
            {"role": "bios", "flag": "-b", "label": "ColecoVision BIOS (required)",
             "exts": [".bin", ".rom"],
             "required": True,
             "hint": "Look for 'ColecoVision BIOS (1982) (No Title Delay Hack)' — it boots faster. "
                     "We can't provide this file; it comes with most ColecoVision game collections / emulator packs."},
            {"role": "splash", "flag": "-s", "label": "Splash screen (optional)",
             "exts": [".raw"],
             "hint": "A 76800-byte raw 240x160 15-bit image shown when the ROM boots."},
        ],
        "options": [
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names."},
            {"flag": "-bb", "label": "Add '-- Empty --' BIOS entry", "help": "Adds a menu entry that boots straight to the ColecoVision BIOS."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "cologne-compilation.gba",
    },
    {
        "id": "msxadvance",
        "name": "MSXAdvance",
        "system": "MSX-1",
        "emoji": "\U0001f4bb",  # 💻
        "tagline": "Play MSX-1 computer games on your Game Boy Advance",
        "description": "MSXAdvance runs MSX-1 computer games. It needs the MSX BIOS (the computer's built-in "
                       "operating system) to start games.",
        "script": "msxadvance_compile.py",
        "roms": {"label": "MSX game ROMs", "exts": [".rom"],
                 "hint": "Add .rom MSX game files. The mapper type is detected automatically."},
        "emu": {"label": "MSXAdvance emulator", "filename": "msxadva.gba",
                "fetch": EZ4_RAW + "/msxadvance02/msxadva.gba",
                "hint": "Use MSXAdvance v0.2 — later versions have compatibility problems."},
        "extras": [
            {"role": "bios", "flag": "-b", "label": "MSX BIOS (required)",
             "exts": [".bin", ".rom"],
             "required": True,
             "hint": "Look for 'MSX System v1.0 + MSX BASIC (1983)(Microsoft)[MSX.ROM]'. "
                     "We can't provide this file; it comes with most MSX emulator packs."},
            {"role": "splash", "flag": "-s", "label": "Splash screen (optional)",
             "exts": [".raw"],
             "hint": "A 76800-byte raw 240x160 15-bit image shown when the ROM boots."},
        ],
        "options": [
            {"flag": "-m", "label": "Mark small games with *", "help": "Marks small ROMs as suitable for link-cable transfer."},
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names."},
            {"flag": "-nomap", "label": "Disable mapper auto-detect", "help": "Turns off automatic mapper selection."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "msxadv-compilation.gba",
    },
    {
        "id": "ngpgba",
        "name": "NGPGBA",
        "system": "Neo Geo Pocket / Pocket Color",
        "emoji": "\U0001f3ae",
        "tagline": "Play Neo Geo Pocket games on your Game Boy Advance",
        "description": "NGPGBA emulates SNK's Neo Geo Pocket and Neo Geo Pocket Color handhelds.",
        "script": "ngpgba_compile.py",
        "roms": {"label": "Neo Geo Pocket ROMs", "exts": [".ngp", ".ngc"],
                 "hint": "Add .ngp (monochrome) and .ngc (Color) game files."},
        "emu": {"label": "NGPGBA emulator", "filename": "NGPGBA.gba",
                "fetch": EZ4_RAW + "/ngpgba055/NGPGBA.gba",
                "hint": "The recommended build is exit-patched for EZ-Flash flashcarts."},
        "extras": [],
        "options": [
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "ngpgba-compilation.gba",
    },
    {
        "id": "wasabi",
        "name": "Wasabi",
        "system": "Watara Supervision",
        "emoji": "\U0001f3ae",
        "tagline": "Play Watara Supervision games on your Game Boy Advance",
        "description": "Wasabi emulates the obscure but fun Watara Supervision handheld.",
        "script": "wasabi_compile.py",
        "roms": {"label": "Supervision ROMs", "exts": [".sv"],
                 "hint": "Add .sv Supervision game files."},
        "emu": {"label": "Wasabi emulator", "filename": "WasabiGBA.gba",
                "fetch": EZ4_RAW + "/wasabi023/WasabiGBA.gba",
                "hint": "The recommended build is exit-patched for EZ-Flash flashcarts."},
        "extras": [],
        "options": [
            {"flag": "-c", "label": "Clean game titles", "help": "Removes (tags) and [tags] from the game names."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "wasabi-compilation.gba",
    },
    {
        "id": "zxadvance",
        "name": "ZXAdvance",
        "system": "Sinclair ZX Spectrum 48K",
        "emoji": "\U0001f4bb",
        "tagline": "Play ZX Spectrum games on your Game Boy Advance",
        "description": "ZXAdvance runs classic ZX Spectrum 48K games. It can load per-game control "
                       "configurations from a ZXA.INI file if you have one.",
        "script": "zxadvance_compile.py",
        "roms": {"label": "ZX Spectrum game files", "exts": [".z80", ".sna"],
                 "hint": "Add .z80 or .sna game snapshots."},
        "emu": {"label": "ZXAdvance emulator", "filename": "zxa.gba",
                "fetch": EZ4_RAW + "/zxadvance101/zxa.gba",
                "hint": "The recommended build is exit-patched for EZ-Flash flashcarts."},
        "extras": [
            {"role": "inifile", "flag": "-i", "label": "ZXA.INI controls file (optional)",
             "exts": [".ini"],
             "hint": "Optional control configuration file (ZXA.INI) from the original ZXAdvance release."},
        ],
        "options": [
            {"flag": "-p", "label": "Make Pogoshell plugin", "help": "Also creates a Pogoshell plugin using the game configurations from ZXA.INI."},
            {"flag": "-c", "label": "Clean the INI file", "help": "Converts [section] entries to lower case and sorts the file."},
            {"flag": "-sav", "label": "Make blank .sav save file", "help": "For EZ-Flash IV firmware 1.x. Creates an empty save file next to your ROM."},
            {"flag": "-pat", "label": "Make .pat save patch", "help": "For EZ-Flash IV firmware 2.x. Forces 64KB SRAM saves."},
        ],
        "output": "zxadv-compilation.gba",
    },
]

BUILDERS_BY_ID = {b["id"]: b for b in BUILDERS}

# Helpful translations for common build-script errors -> plain language
FRIENDLY_ERRORS = [
    ("unsupported filetype for compilation",
     "One of the files you added isn't a game this builder understands. Check the file types listed in Step 2."),
    ("can't open",
     "A needed file is missing or can't be opened. Check that you added all required files."),
    ("No such file or directory",
     "A needed file is missing. Check that you added all required files."),
    ("UnicodeEncodeError",
     "A game name contains special characters that the builder can't use. Try renaming the file with plain letters."),
    ("index out of range",
     "One of the files seems to be the wrong format or possibly corrupted/truncated."),
    ("struct.error",
     "One of the files seems to be the wrong format or possibly corrupted/truncated."),
]


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def sanitize_filename(name, fallback="file.bin"):
    """Keep only a safe basename; avoid path tricks. Non-ASCII letters are
    transliterated because the builder scripts write ASCII-only game titles."""
    name = os.path.basename((name or "").replace("\\", "/")).strip().strip(".")
    if not name or name in ("..", "."):
        return fallback
    # transliterate accents (Pokémon -> Pokemon) and drop anything unencodable
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", ascii_name)
    ascii_name = re.sub(r"\s+", " ", ascii_name).strip()
    if not ascii_name or ascii_name in ("..", "."):
        return fallback
    return ascii_name


def valid_job_id(job):
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", job or ""))


def job_dir(job):
    return os.path.join(JOBS_DIR, job)


def uploads_dir(job):
    return os.path.join(job_dir(job), "uploads")


def out_dir(job):
    return os.path.join(job_dir(job), "out")


def human_size(n):
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024.0
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def friendly_message(log):
    for needle, msg in FRIENDLY_ERRORS:
        if needle in (log or ""):
            return msg
    return "Something went wrong during the build. Have a look at the details below."


# --------------------------------------------------------------------------
# Registry access (same JSON for server mode and browser mode)
# --------------------------------------------------------------------------

def get_builders_json():
    return json.dumps(BUILDERS)


# --------------------------------------------------------------------------
# Build runner
# --------------------------------------------------------------------------

def extract_hvca_bin(archive_or_dir, job):
    """Return the folder that contains base.bin for HVCA."""
    if os.path.isdir(archive_or_dir):
        return archive_or_dir
    work = os.path.join(job_dir(job), "bin")
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work, exist_ok=True)
    if zipfile.is_zipfile(archive_or_dir):
        with zipfile.ZipFile(archive_or_dir) as zf:
            zf.extractall(work)
    elif tarfile.is_tarfile(archive_or_dir):
        with tarfile.open(archive_or_dir) as tf:
            tf.extractall(work)
    else:
        raise ApiError("HVCA needs its emulator files as a .zip (containing base.bin).")
    # find the folder holding base.bin
    for root, _dirs, files in os.walk(work):
        if "base.bin" in files:
            return root
    raise ApiError("That archive doesn't look like HVCA emulator files — base.bin was not found inside.")


def build_command(builder, job, payload):
    """Translate the UI payload into the script's command line (no interpreter)."""
    updir = uploads_dir(job)
    odir = out_dir(job)
    os.makedirs(odir, exist_ok=True)

    files = payload.get("files") or {}
    roms = payload.get("roms") or []
    options = payload.get("options") or {}
    flags = [f for f in (options.get("flags") or [])]

    if not roms:
        raise ApiError("Add at least one game ROM before building.")

    # validate ROMs first — the most common beginner mistake gets the clearest message
    rom_exts = builder["roms"]["exts"]
    rom_paths = []
    for r in roms:
        safe = sanitize_filename(r)
        p = os.path.join(updir, safe)
        if not os.path.isfile(p):
            raise ApiError(f"Game file not found: {r}")
        if os.path.splitext(safe)[1].lower() not in rom_exts:
            raise ApiError(f"'{safe}' is not a file type this builder accepts ({', '.join(rom_exts)}).")
        rom_paths.append(p)

    script = os.path.join(REPO_DIR, builder["script"])
    if not os.path.exists(script):
        raise ApiError(f"Build script not found: {builder['script']} (is the gba-emu-compilation-builders repo next to this app?)", 500)

    cmd = [script]

    # --- emulator binary / folder -----------------------------------------
    emu_name = files.get("emu")
    if emu_name == "__AUTO__":
        raise ApiError("Resolve the automatic emulator download before building.")
    if not emu_name:
        raise ApiError("Add the emulator file (or press 'Download for me') before building.")
    emu_path = os.path.join(updir, sanitize_filename(emu_name))
    if builder["id"] == "hvca":
        if not os.path.exists(emu_path):
            raise ApiError("HVCA emulator files are missing. Press 'Download for me' or upload the folder as a .zip.")
        emu_path = extract_hvca_bin(emu_path, job)
    elif not os.path.isfile(emu_path):
        raise ApiError("The emulator file is missing. Add it in Step 2.")
    cmd += ["-e", emu_path]

    # --- side files (bios, splash, ini, ...) -------------------------------
    extras_by_role = {e["role"]: e for e in builder.get("extras", [])}
    has_fds = any(r.lower().endswith(".fds") for r in roms)
    has_iso = any(r.lower().endswith(".iso") for r in roms)

    def role_names(role):
        """UI sends one name or a list of names per role -> normalise to a list."""
        val = files.get(role)
        if val is None:
            return []
        if isinstance(val, str):
            return [val] if val else []
        return [n for n in val if n]

    bios_names = role_names("bios")
    bios_paths = [os.path.join(updir, sanitize_filename(n)) for n in bios_names]
    bios_paths = [p for p in bios_paths if os.path.isfile(p)]
    cdrombios_paths = [os.path.join(updir, sanitize_filename(n))
                       for n in role_names("cdrombios")]
    cdrombios_paths = [p for p in cdrombios_paths if os.path.isfile(p)]

    bios_extra = extras_by_role.get("bios")
    if bios_extra and bios_extra.get("required") and not bios_paths:
        raise ApiError(f"{bios_extra['label']} is required for this builder — please add it in Step 2.")
    if builder["id"] == "hvca" and has_fds and not bios_paths:
        raise ApiError("FDS games (.fds) need the FDS BIOS file (disksys.rom) — please add it in Step 2.")
    if builder["id"] == "pceadvance" and has_iso and not cdrombios_paths:
        raise ApiError("CD-ROM games (.iso) need the PC Engine CD-ROM BIOS — please add it in Step 2.")

    sms_bios_late = False  # smsadvance bios must come AFTER the rom files
    for role, extra in extras_by_role.items():
        if role in ("splash", "exitsub", "palette", "inifile", "tcd", "cdrombios"):
            names = role_names(role)
            if not names:
                continue
            path = os.path.join(updir, sanitize_filename(names[0]))
            if not os.path.isfile(path):
                raise ApiError(f"Missing file: {names[0]}")
            cmd += [extra["flag"], path]
        elif role == "bios" and extra.get("flag") == "-b":
            if builder["id"] == "smsadvance":
                sms_bios_late = bool(bios_paths)
            elif builder["id"] == "hvca":
                # always pass -b (the script errors if the default is missing);
                # a placeholder is harmless unless an .fds game is present
                if bios_paths:
                    cmd += ["-b", bios_paths[0]]
                else:
                    placeholder = os.path.join(updir, "no-bios-needed.bin")
                    if not os.path.exists(placeholder):
                        open(placeholder, "wb").close()
                    cmd += ["-b", placeholder]
            elif bios_paths:
                cmd += ["-b", bios_paths[0]]

    # bundled HVCA exit subroutine (not an upload)
    if builder["id"] == "hvca" and "hvca-exit" in flags:
        flags.remove("hvca-exit")
        sub = os.path.join(REPO_DIR, "flash_ez4_ezo.sub")
        if os.path.exists(sub):
            cmd += ["-x", sub]

    # --- switches -----------------------------------------------------------
    valid_flags = {o["flag"] for o in builder.get("options", [])}
    for flag in flags:
        if flag in valid_flags and flag != "hvca-exit":
            cmd.append(flag)

    # --- output name --------------------------------------------------------
    out_name = sanitize_filename(options.get("output") or "", fallback="")
    if builder["id"] == "snezziboy" and len(roms) > 1:
        out_name = ""   # one output per game; -o only allowed for a single ROM
    elif not out_name:
        out_name = builder["output"] or "compilation.gba"
    if out_name:
        if not out_name.lower().endswith(".gba"):
            out_name += ".gba"
        cmd += ["-o", out_name]

    # --- ROMs (absolute paths, in the user's order) -------------------------
    cmd += rom_paths

    if sms_bios_late:
        cmd += ["-b"] + bios_paths

    return cmd


def subprocess_executor(cmd, cwd):
    """Run a builder script in a subprocess (server/host mode)."""
    try:
        proc = subprocess.run(
            [sys.executable] + list(cmd), cwd=cwd, timeout=BUILD_TIMEOUT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        return proc.returncode, proc.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return 124, "The build took too long and was stopped."


# Hosts may replace this (Pyodide installs a runpy-based executor).
EXECUTOR = subprocess_executor


def run_build(builder, job, payload):
    """Run one build. Returns a plain dict (serialisable)."""
    try:
        cmd = build_command(builder, job, payload)
    except ApiError as e:
        return {"ok": False, "log": "", "outputs": [], "message": str(e)}

    odir = out_dir(job)
    code, log = EXECUTOR(cmd, odir)
    ok = code == 0

    if code == 124:
        return {"ok": False, "log": log,
                "message": "The build timed out. Try fewer or smaller games."}

    outputs = []
    try:
        for name in sorted(os.listdir(odir)):
            path = os.path.join(odir, name)
            if os.path.isfile(path):
                outputs.append({
                    "name": name,
                    "size": os.path.getsize(path),
                    "size_h": human_size(os.path.getsize(path)),
                })
    except OSError:
        pass

    if ok and not any(o["name"].lower().endswith(".gba") for o in outputs):
        ok = False

    return {
        "ok": ok,
        "log": log,
        "outputs": outputs if ok else [],
        "message": None if ok else friendly_message(log),
    }


def run_build_json(payload_json):
    """JSON-in / JSON-out wrapper used by the in-browser (Pyodide) host."""
    try:
        payload = json.loads(payload_json)
    except ValueError:
        return json.dumps({"ok": False, "message": "Invalid request data."})
    builder = BUILDERS_BY_ID.get(payload.get("builder") or "")
    job = payload.get("job") or ""
    if not builder:
        return json.dumps({"ok": False, "message": "Unknown builder."})
    if not valid_job_id(job):
        return json.dumps({"ok": False, "message": "Bad job id."})
    result = run_build(builder, job, payload)
    # browser hosts fetch outputs by name from the virtual FS; keep the URLs
    # too so the JSON shape matches the server API
    for o in result.get("outputs", []):
        o["url"] = f"/api/jobs/{job}/out/{o['name']}"
    return json.dumps(result)
