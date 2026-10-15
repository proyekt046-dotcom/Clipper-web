#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLIPPER OTOMATIS - versi web
Unduh, potong, gabung, dan jadikan vertikal 9:16 (TikTok / Reels / Shorts)
Logika inti sama persis dengan versi command-line, dibungkus jadi web app
dengan proses di background (job queue sederhana) supaya tidak kena
timeout saat di-deploy ke hosting gratis.
"""

import glob
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS

LEBAR, TINGGI, FPS = 1080, 1920, 30

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "hasil")
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)
CORS(app)

# job_id -> {"status", "pesan", "file", "dibuat"}
JOBS = {}
JOBS_LOCK = threading.Lock()


def bersihkan_teks_ffmpeg(teks):
    teks = teks.replace('\\', '\\\\').replace(':', '\\:').replace("'", "'\\\\''")
    return re.sub(r'([,;=])', r'\\\1', teks)

def tambah_filter_hook(filter_sekarang, teks_hook):
    if not teks_hook:
        return filter_sekarang
    teks_aman = bersihkan_teks_ffmpeg(teks_hook)
    filter_teks = (
        f"drawtext=text='{teks_aman}':fontcolor=white:fontsize=48:fontfile=Arial:"
        f"box=1:boxcolor=red@0.8:boxborderw=20:"
        f"x=(w-tw)/2:y=250:enable='lte(t,3)'"
    )
    return f"{filter_sekarang},{filter_teks}"
# ----------------------------------------------------------------------
# Bantuan waktu (identik dengan versi CLI)
# ----------------------------------------------------------------------
def ke_detik(teks):
    bagian = teks.strip().split(":")
    if not 1 <= len(bagian) <= 3:
        raise ValueError(f"Format waktu salah: '{teks}'")
    total = 0.0
    for b in bagian:
        try:
            total = total * 60 + float(b)
        except ValueError:
            raise ValueError(f"Format waktu salah: '{teks}'") from None
    return total


def parse_potongan(teks):
    teks = teks.replace("\u2013", "-").replace("\u2014", "-")
    bagian = teks.split("-")
    if len(bagian) != 2:
        raise ValueError(f"Format salah: '{teks}'. Contoh yang benar: 27:01-27:36")
    mulai, selesai = ke_detik(bagian[0]), ke_detik(bagian[1])
    if selesai <= mulai:
        raise ValueError(f"Waktu akhir harus lebih besar dari waktu mulai: '{teks}'")
    return mulai, selesai


def angka(detik):
    return str(int(detik)) if float(detik).is_integer() else f"{detik:.3f}"


# ----------------------------------------------------------------------
# Cek alat
# ----------------------------------------------------------------------
def cari_ffmpeg():
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def cek_yt_dlp():
    if importlib.util.find_spec("yt_dlp") is None:
        raise RuntimeError('yt-dlp belum terpasang di server.')


def opsi_js_runtime():
    if shutil.which("deno"):
        return []
    node = shutil.which("node")
    if node:
        try:
            versi = subprocess.run([node, "-v"], capture_output=True, text=True).stdout.strip()
            utama = int(versi.lstrip("v").split(".")[0])
        except Exception:
            utama = 0
        if utama >= 22:
            return ["--js-runtimes", "node"]
    return []


# ----------------------------------------------------------------------
# Unduh hanya bagian yang dibutuhkan
# ----------------------------------------------------------------------
def unduh_potongan(url, mulai, selesai, folder, ffmpeg, js_opsi):
    os.makedirs(folder, exist_ok=True)
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "--download-sections", f"*{angka(mulai)}-{angka(selesai)}",
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format", "mp4",
        "--ffmpeg-location", ffmpeg,
        "-o", os.path.join(folder, "potongan.%(ext)s"),
        *js_opsi,
        url,
    ]
    proses = subprocess.run(cmd, capture_output=True, text=True)
    if proses.returncode != 0:
        raise RuntimeError(
            "Gagal mengunduh. Kemungkinan: link belum lengkap, video privat/dibatasi, "
            "atau server butuh update yt-dlp.\n" + proses.stderr[-800:]
        )
    kandidat = [
        p for p in glob.glob(os.path.join(folder, "*"))
        if p.lower().endswith((".mp4", ".mkv", ".webm", ".mov")) and not re.search(r"\.f\d+\.", p)
    ]
    if not kandidat:
        raise RuntimeError("Unduhan selesai tapi file hasilnya tidak ditemukan.")
    return max(kandidat, key=os.path.getsize)


# ----------------------------------------------------------------------
# Gabung + jadikan 9:16 dengan FFmpeg
# ----------------------------------------------------------------------
def bangun_filter(n, mode, posisi):
    bagian = []
    for i in range(n):
        if mode == "crop":
            video = (
                f"[{i}:v]setpts=PTS-STARTPTS,"
                f"scale={LEBAR}:{TINGGI}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={LEBAR}:{TINGGI}:x=(iw-ow)*{posisi}:y=(ih-oh)/2,"
                f"setsar=1,fps={FPS},format=yuv420p[v{i}]"
            )
        else:
            video = (
                f"[{i}:v]setpts=PTS-STARTPTS,split=2[s{i}a][s{i}b];"
                f"[s{i}a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                f"boxblur=10:3,scale={LEBAR}:{TINGGI}[bg{i}];"
                f"[s{i}b]scale={LEBAR}:{TINGGI}:force_original_aspect_ratio=decrease:flags=lanczos[fg{i}];"
                f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS},format=yuv420p[v{i}]"
            )
        audio = f"[{i}:a]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a{i}]"
        bagian += [video, audio]
    urutan = "".join(f"[v{i}][a{i}]" for i in range(n))
    bagian.append(f"{urutan}concat=n={n}:v=1:a=1[v][a]")
    return ";".join(bagian)


def render(ffmpeg, masukan, mode, posisi, output, teks_hook=''):
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for m in masukan:
        cmd += m
    cmd += [
        "-filter_complex", tambah_filter_hook(bangun_filter(len(masukan), mode, posisi), teks_hook),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output,
    ]
    proses = subprocess.run(cmd, capture_output=True, text=True)
    if proses.returncode != 0:
        raise RuntimeError(
            "Gagal menggabungkan video. Pastikan video sumber punya suara dan waktunya benar.\n"
            + proses.stderr[-800:]
        )


# ----------------------------------------------------------------------
# Job di background
# ----------------------------------------------------------------------
def set_job(job_id, **kv):
    with JOBS_LOCK:
        JOBS[job_id].update(kv)


def jalankan_job(job_id, sumber, potongan, mode, posisi, nama_output, visual_hook=''):
    try:
        lokal = os.path.isfile(sumber)
        ffmpeg = cari_ffmpeg()
        nama_file_akhir = f"{job_id}_{nama_output}"
        output_path = os.path.join(OUTPUT_DIR, nama_file_akhir)

        with tempfile.TemporaryDirectory(prefix="clipper_") as tmp:
            masukan = []
            if lokal:
                set_job(job_id, status="menyiapkan", pesan="Menyiapkan...")
                for mulai, selesai in potongan:
                    masukan.append(["-ss", angka(mulai), "-t", angka(selesai), "-i", sumber])
            else:
                cek_yt_dlp()
                js_opsi = opsi_js_runtime()
                for n, (mulai, selesai) in enumerate(potongan, 1):
                    set_job(job_id, status="mengunduh",
                            pesan=f"Mengunduh bagian {n}/{len(potongan)}...")
                    berkas = unduh_potongan(sumber, mulai, selesai, tmp, ffmpeg, js_opsi)
                    masukan.append(["-i", berkas])

            set_job(job_id, status="menggabung", pesan="Menggabungkan video...")
            render(ffmpeg, masukan, mode, posisi, output_path, visual_hook)

        set_job(job_id, status="sukses", pesan="Selesai!", file_name=nama_file_akhir)
    except Exception as e:
        set_job(job_id, status="gagal", pesan=str(e)
    ) 

# ----------------------------------------------------------------------
# Rute web
# ----------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/proses", methods=["POST"])
def proses():
    data = request.get_json(force=True, silent=True) or {}
    sumber = (data.get("sumber") or "").strip().strip('"').strip("'")
    potong_mentah = data.get("potong") or []
    mode = data.get("mode") if data.get("mode") in ("crop", "blur") else "crop"
   visual_hook = data.get("visual_hook", "")
        posisi = min(1.0, max(0.0, float(data.get("posisi", 0.5))))
    except (TypeError, ValueError):
        posisi = 0.5
    nama_output = (data.get("output") or "klip_vertikal.mp4").strip() or "klip_vertikal.mp4"
    if not nama_output.lower().endswith(".mp4"):
        nama_output += ".mp4"
    nama_output = re.sub(r"[^\w.\-]", "_", nama_output)

    if not sumber:
        return jsonify({"error": "Link YouTube atau path file wajib diisi."}), 400

    lokal = os.path.isfile(sumber)
    if not lokal and not sumber.lower().startswith(("http://", "https://")):
        return jsonify({"error": f"Sumber tidak dikenali: '{sumber}'."}), 400

    try:
        potongan = [parse_potongan(t) for t in potong_mentah if t and t.strip()]
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not potongan:
        return jsonify({"error": "Minimal isi satu potongan waktu."}), 400

    job_id = uuid.uuid4().hex[:10]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "menunggu", "pesan": "Menunggu giliran...", "file": None, "dibuat": time.time()}
     t = threading.Thread(target=jalankan_job, args=(job_id, sumber, potongan, mode, posisi, nama_output, visual_hook), daemon=True)
  
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job tidak ditemukan."}), 404
    return jsonify(job)


@app.route("/unduh/<path:nama_file>")
def unduh(nama_file):
    return send_from_directory(OUTPUT_DIR, nama_file, as_attachment=True)


@app.route("/health")
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
