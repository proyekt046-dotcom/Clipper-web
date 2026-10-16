import os
import subprocess
import requests
import json
import re
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

OUTPUT_DIR = "static/hasil"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# KUNCI API ANDA
GEMINI_API_KEY = "AQ.Ab8RN6iEwvknyGPEWcS5*"
GROQ_API_KEY = "MASUKKAN_API_KEY_GROQ_ANDA_DISINI"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/proses', methods=['POST'])
def proses_video():
    data = request.json
    url = data.get('url')
    mode_cut = data.get('mode_cut', 'manual')
    mulai_manual = data.get('mulai', '00:00')
    selesai_manual = data.get('selesai', '00:30')
    teks_hook_manual = data.get('teks_hook', '')
    mode_tampilan = data.get('mode', 'crop')
    warna_sub = data.get('warna_sub', 'yellow')
    campaign_target = data.get('campaign_target', '')

    # Bersihkan folder hasil lama
    for f in os.listdir(OUTPUT_DIR):
        try: os.remove(os.path.exists(os.path.join(OUTPUT_DIR, f)))
        except: pass

    try:
        # 1. Unduh video asli menggunakan yt-dlp beserta metadata
        import yt_dlp
        output_download = os.path.join(OUTPUT_DIR, "video_asli.mp4")
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'outtmpl': output_download,
            'writesubtitles': True,
            'writeautosubtitles': True,
            'subtitlesformat': 'srt',
            'skip_download': False
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            judul_video = info_dict.get('title', '')
            deskripsi_video = info_dict.get('description', '')

        list_potongan = []

        # 2. LOGIKA MULTI-CLIP & AUTO CUT VIA GEMINI
        if mode_cut == 'auto':
            url_api = f"https://googleapis.com{GEMINI_API_KEY}"
            headers = {'Content-Type': 'application/json'}
            
            prompt_ai = (
                f"Video berjudul '{judul_video}' deskripsi: '{deskripsi_video}'. "
                f"Tugas utama: Cari dan tentukan 3 segmen momen terbaik yang PALING RELEVAN dengan Target Campaign: '{campaign_target}'. "
                "Setiap potongan klip (durasi 20-40 detik) harus fokus membahas topik campaign tersebut dan memiliki 'hook' yang sangat kuat untuk konten tiktok viral. "
                "Berikan jawaban HANYA berupa array JSON mentah berformat seperti ini tanpa markdown atau teks tambahan: "
                '[{"mulai": "01:20", "selesai": "01:50", "teks_hook": "Judul Hook 1", "skor": 95, "alasan": "Alasan viral 1"}, '
                '{"mulai": "03:10", "selesai": "03:40", "teks_hook": "Judul Hook 2", "skor": 88, "alasan": "Alasan viral 2"}, '
                '{"mulai": "05:15", "selesai": "05:45", "teks_hook": "Judul Hook 3", "skor": 91, "alasan": "Alasan viral 3"}]'
            )

            payload = {"contents": [{"parts": [{"text": prompt_ai}]}]}
            response = requests.post(url_api, headers=headers, json=payload)
            res_json = response.json()
            teks_json = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            teks_json = teks_json.replace("```json", "").replace("```", "").strip()
            list_potongan = json.loads(teks_json)
        else:
            # Jika mode manual
            list_potongan = [{
                "mulai": mulai_manual,
                "selesai": selesai_manual,
                "teks_hook": teks_hook_manual,
                "skor": 100,
                "alasan": "Dipotong secara manual oleh pengguna."
            }]

        hasil_klip_final = []

        # 3. PROSES PEMOTONGAN MASSAL (LOOPING MULTI-CLIP)
        for index, klip in enumerate(list_potongan):
            t_mulai = klip.get('mulai')
            t_selesai = klip.get('selesai')
            t_hook = klip.get('teks_hook', '')

            if t_mulai.count(':') == 1: t_mulai = f"00:{t_mulai}"
            if t_selesai.count(':') == 1: t_selesai = f"00:{t_selesai}"

            output_potong = os.path.join(OUTPUT_DIR, f"temp_{index}.mp4")
            filename_hasil = f"klip_viral_{index+1}.mp4"
            output_final_klip = os.path.join(OUTPUT_DIR, filename_hasil)

            # Potong video menggunakan FFmpeg via subprocess
            cmd_cut = [
                'ffmpeg', '-y', '-ss', t_mulai, '-to', t_selesai, 
                '-i', output_download, '-c', 'copy', output_potong
            ]
            subprocess.run(cmd_cut, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Logika Cropping Vertikal (9:16) untuk TikTok
            if mode_tampilan == 'crop':
                cmd_render = [
                    'ffmpeg', '-y', '-i', output_potong, 
                    '-vf', "scale=ih*9/16:ih,scale=1080:1920", 
                    '-c:v', 'libx264', '-profile:v', 'main', '-level:v', '4.0',
                    '-crf', '23', '-c:a', 'aac', '-ar', '44100', output_final_klip
                ]
            else:
                # Mode Blur Latar Belakang
                cmd_render = [
                    'ffmpeg', '-y', '-i', output_potong, 
                    '-vf', "split[v1][v2];[v1]scale=1080:1920,boxblur=20[bg];[v2]scale=1080:-1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2", 
                    '-c:v', 'libx264', '-crf', '23', '-c:a', 'aac', output_final_klip
                ]
            
            subprocess.run(cmd_render, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Tambahkan ke daftar hasil sukses
            hasil_klip_final.append({
                "klip_video_url": f"/static/hasil/{filename_hasil}",
                "mulai": klip.get('mulai'),
                "selesai": klip.get('selesai'),
                "teks_hook": t_hook,
                "skor": klip.get('skor', 100),
                "alasan": klip.get('alasan', '')
            })

            # Hapus file sampah sementara
            if os.path.exists(output_potong):
                os.remove(output_potong)

        return jsonify({"status": "Sukses", "data": hasil_klip_final})

    except Exception as e:
        return jsonify({"status": "Gagal", "error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
