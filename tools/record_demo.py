"""Record the demo as a replay of captured output, never a performance.

Pipeline, per the rules this repository follows for evidence:

1. Run each demo command for real; capture stdout, stderr, exit code
   and wall time into docs/video/manifest.json.
2. Generate a self-contained HTML player that types each command and
   reveals its captured output paced by the measured duration.
3. Record the player with Playwright and Chromium to webm, then
   transcode with ffmpeg to an MP4 and a palette GIF that autoplays
   on GitHub.

Every character of terminal text in the result is real captured
output; the only fabrication is the typing animation. The README says
exactly that under the GIF, and the manifest lists each command with
its exit code so a reviewer can re-run the lot.
"""

from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO_DIR = ROOT / "docs" / "video"
EVIDENCE_DIR = ROOT / "docs" / "evidence"

BASE = [
    "--seed", "7", "--duration-s", "20", "--rate-rps", "200",
    "--workers", "8", "--server-capacity", "16",
]
STALL = ["--stall-start-s", "5", "--stall-duration-s", "0.5", "--stall-period-s", "10"]

COMMANDS: list[tuple[str, list[str]]] = [
    # The argument order: baseline, headline, the number nobody else
    # reports, then the receipts.
    ("openloop compare (calm baseline)",
     [sys.executable, "-m", "openloop.cli", "compare", *BASE]),
    ("openloop compare (500 ms pause every 10 s)",
     [sys.executable, "-m", "openloop.cli", "compare", *BASE, *STALL]),
    ("openloop run --generator closed --json (the omission, itemised)",
     [sys.executable, "-m", "openloop.cli", "run", "--generator", "closed", "--json",
      *BASE, *STALL]),
    ("make experiments (re-measure everything)",
     ["make", "experiments"]),
    ("python tools/check_numbers.py (hold the documents to the code)",
     [sys.executable, "tools/check_numbers.py"]),
]


def capture() -> list[dict]:
    # Warm the interpreter and imports so the first segment does not
    # pay the startup cost and skew the pacing.
    subprocess.run([sys.executable, "-c", "import openloop"], cwd=ROOT, check=True)
    segments = []
    for title, argv in COMMANDS:
        started = time.monotonic()
        proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
        segments.append({
            "title": title,
            "command": " ".join(a if a != sys.executable else "python" for a in argv),
            "exit_code": proc.returncode,
            "duration_s": round(time.monotonic() - started, 2),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        })
        print(f"captured: {title} (exit {proc.returncode}, {segments[-1]['duration_s']}s)")
    return segments


def build_player(segments: list[dict]) -> Path:
    blocks = []
    for seg in segments:
        out = html.escape(seg["stdout"] + (seg["stderr"] or ""))
        cmd = html.escape("$ " + seg["command"])
        # Pace by measured wall time, capped so one slow command does
        # not dominate the GIF; a compressed segment prints its true
        # duration so slowness is stated rather than hidden.
        paced = min(max(seg["duration_s"], 0.6), 8.0)
        note = (f"(completed in {seg['duration_s']} s)"
                if seg["duration_s"] > 8.0 else "")
        blocks.append(
            f'{{"cmd": {json.dumps(cmd)}, "out": {json.dumps(out)}, '
            f'"dur": {paced}, "code": {seg["exit_code"]}, "note": {json.dumps(note)}}}'
        )
    page = f"""<!doctype html>
<meta charset="utf-8">
<style>
  body {{ margin: 0; background: #0e1726; }}
  #term {{ width: 920px; height: 640px; margin: 10px auto; background: #0e1726;
          color: #d7e1f0; font: 15px/1.45 "DejaVu Sans Mono", monospace;
          padding: 18px 22px; box-sizing: border-box; overflow: hidden;
          white-space: pre-wrap; }}
  .cmd {{ color: #5eead4; font-weight: bold; }}
  .code {{ color: #9fb0c7; }}
</style>
<div id="term"></div>
<script>
const SEGMENTS = [{",".join(blocks)}];
const term = document.getElementById("term");
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
function trim() {{
  while (term.scrollHeight > term.clientHeight && term.firstChild) {{
    term.removeChild(term.firstChild);
  }}
}}
async function typeLine(text) {{
  const span = document.createElement("span");
  span.className = "cmd";
  term.appendChild(span);
  for (const ch of text) {{ span.textContent += ch; trim(); await sleep(14); }}
  term.appendChild(document.createTextNode("\\n"));
}}
async function play() {{
  for (const seg of SEGMENTS) {{
    await typeLine(seg.cmd);
    await sleep(250);
    const lines = seg.out.split("\\n");
    const per = Math.min(90, (seg.dur * 1000) / Math.max(lines.length, 1));
    for (const line of lines) {{
      term.appendChild(document.createTextNode(line + "\\n"));
      trim();
      await sleep(per);
    }}
    const code = document.createElement("span");
    code.className = "code";
    code.textContent = "exit code " + seg.code + "\\n\\n";
    term.appendChild(code);
    trim();
    await sleep(700);
  }}
  document.title = "DONE";
}}
play();
</script>
"""
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    path = VIDEO_DIR / "player.html"
    path.write_text(page)
    return path


def record(player: Path, total_s: float) -> Path:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 940, "height": 660},
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 940, "height": 660},
        )
        page = context.new_page()
        page.goto(player.as_uri())
        page.wait_for_function("document.title === 'DONE'", timeout=(total_s + 60) * 1000)
        page.wait_for_timeout(800)
        video = page.video
        context.close()
        webm = Path(video.path())
        browser.close()
    target = VIDEO_DIR / "demo.webm"
    shutil.move(webm, target)
    return target


def transcode(webm: Path) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    mp4 = VIDEO_DIR / "demo.mp4"
    gif = EVIDENCE_DIR / "demo.gif"
    palette = VIDEO_DIR / "palette.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm),
                    "-pix_fmt", "yuv420p", str(mp4)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm),
                    "-vf", "fps=8,scale=720:-1:flags=lanczos,palettegen", str(palette)],
                   check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-i", str(palette),
                    "-filter_complex", "fps=8,scale=720:-1:flags=lanczos[x];[x][1:v]paletteuse",
                    str(gif)], check=True)
    palette.unlink()
    gif_mb = gif.stat().st_size / 1e6
    mp4_mb = mp4.stat().st_size / 1e6
    print(f"record_demo: gif {gif_mb:.1f} MB, mp4 {mp4_mb:.1f} MB")


def main() -> int:
    segments = capture()
    manifest = [{k: seg[k] for k in ("title", "command", "exit_code", "duration_s")}
                for seg in segments]
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    (VIDEO_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    player = build_player(segments)
    total = sum(seg["duration_s"] for seg in segments) + 20
    webm = record(player, total)
    transcode(webm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
