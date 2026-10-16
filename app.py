import os
import subprocess
import requests
import json
import re
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

OUTPUT_DIR = "static/hasils"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# KUNCI API ANDA (Pastikan kodenya utuh di dalam tanda petik)
GEMINI_API_KEY = "AQ.Ab8RN6IEWvky6PEWcSs5"
GROQ_API_KEY = "MASUKKAN_API_KEY_GROQ_ANDA_DISINI" # Opsional untuk subtitle super akurat, jika kosong akan pakai transkrip bawaan youtube

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
    
    # Bersihkan folder hasil lama
    for f in os.listdir(OUTPUT_DIR):
        try: os.remove(os.path.join(OUTPUT_DIR, f))
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
                "Temukan 3 segmen momen paling menarik (durasi masing-masing 20-40 detik) untuk konten TikTok viral. "
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
            # Jika mode manual, buat jadi 1 item list agar jalurnya sama
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
            
            # Potong durasi awal
            subprocess.run(f"ffmpeg -i {output_download} -ss {t_mulai} -to {t_selesai} -c copy {output_potong} -y", shell=True, check=True)
            
            # Tentukan filter dasar 9:16 (Crop atau Blur)
            if mode_tampilan == "crop":
                base_filter = "crop=ih*9/16:ih"
            else:
                base_filter = "split[v1][v2];[v1]scale=ih*9/16:ih,boxblur=20[bg];[v2]scale=-1:ih[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,crop=ih*9/16:ih"
            
            # FITUR AUTO-SUBTITLE & VISUAL HOOK VIA FFmpeg FILTER
            filter_commands = [base_filter]
            
            # Efek Visual Hook (Muncul 4 detik pertama di tengah atas)
            if t_hook:
                t_hook_aman = t_hook.replace("'", "").replace('"', '')
                filter_commands.append(f"drawtext=text='{t_hook_aman}':fontcolor=white:fontsize=36:box=1:boxcolor=red@0.8:boxborderw=12:x=(w-tw)/2:y=150:enable='lte(t,4)'")
            
            # Efek Auto-Caption (Subtitle Statis di tengah bawah jika transkrip bawaan ada)
            # Untuk kesederhanaan Termux tanpa modul berat, kita sematkan subtitle dasar warna pilihan
            if t_hook:
                sub_text = "IKLAN BRAND PREMIUM" if mode_cut == 'manual' else t_hook_aman
                filter_commands.append(f"drawtext=text='{sub_text}':fontcolor={warna_sub}:fontsize=28:x=(w-tw)/2:y=h-200:enable='gte(t,2)'")

            filter_full = ",".join(filter_commands)
            ffmpeg_cmd = f"ffmpeg -i {output_potong} -vf \"{filter_full}\" -c:v libx264 -crf 23 -c:a aac {output_final_klip} -y"
            subprocess.run(ffmpeg_cmd, shell=True, check=True)
            
            # Hapus file temp per klip
            if os.path.exists(output_potong): os.remove(output_potong)
            
            hasil_klip_final.append({
                "video_url": f"/static/hasils/{filename_hasil}",
                "mulai": t_mulai.replace("00:", ""),
                "selesai": t_selesai.replace("00:", ""),
                "teks_hook": t_hook,
                "skor": klip.get('skor', 90),
                "alasan": klip.get('alasan', '')
            })
            
        if os.path.exists(output_download): os.remove(output_download)
        
        return jsonify({"status": "Sukses", "klips": hasil_klip_final})
        
    except Exception as e:
        return jsonify({"status": "Gagal", "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
