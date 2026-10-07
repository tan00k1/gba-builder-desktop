# GBA Compilation Builder - Windows desktop app

A normal offline Windows program (no browser, no Python needed on the user's
PC) that wraps the builder scripts from
[patters-match/gba-emu-compilation-builders](https://github.com/patters-match/gba-emu-compilation-builders).

Pick a console -> add your games -> add the emulator -> press **Build**.
You get a `.gba` ROM (plus `.sav` / `.pat` files if you tick those options)
for a flash cart or emulator. It produces the same bytes as running the
original scripts by hand.

## Getting the .exe (one-time, about 10 minutes, no coding)

GitHub will build the Windows program for you, for free.

1. Make a free account at https://github.com and click **New repository**
   (name it anything, e.g. `gba-builder-desktop`; Public or Private both work).
2. On the new repository page click **uploading an existing file**.
   Open this folder on your computer and drag **everything inside it**
   (`app.py`, `engine.py`, `gui.py`, `builder_core.py`, the `builders` folder,
   the `tests` folder, the `.txt` file, this README) into the browser window.
   Wait for the uploads to finish, then click **Commit changes**.
3. Add the build instructions file. Click **Add file -> Create new file**.
   In the name box type exactly:  `.github/workflows/build-windows.yml`
   (typing the `/` makes the folders). Open
   `PASTE-INTO-GITHUB_build-windows.yml.txt` from this folder, copy all of it,
   paste it into the big text box, then click **Commit changes**.
4. Click the **Actions** tab. If asked, click the green button to enable
   workflows. Choose **Build Windows app** on the left, then
   **Run workflow -> Run workflow**.
5. Wait about 3-5 minutes. A green tick means success. Click the finished run,
   scroll to **Artifacts**, and download **GBABuilder-Windows**.
   Unzip it - inside is `GBABuilder.exe`.

If the run shows a red X, click it, open the failed step, and send me the text.
The "Self-test" step runs the finished program against real test ROMs, so a
green tick means the packaged program really can build.

## Using it

Double-click `GBABuilder.exe`. Windows may show "Windows protected your PC"
because the program isn't signed by a paid publisher - click **More info ->
Run anyway**. Some antivirus programs also distrust any freshly packaged
Python program; that is a false alarm.

* The **first time** you can press *Download for me* to fetch the recommended
  emulator (needs internet once). It is saved on the PC, so every later build
  works fully offline. You can always choose your own emulator file instead.
* BIOS files (ColecoVision, MSX, FDS, etc.) can't be bundled - you supply them.
* Use only game and BIOS files you legally own.
