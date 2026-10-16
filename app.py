import os
import subprocess
import requests
import json
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

OUTPUT_DIR = "static/hasils"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# API Key Google Gemini Anda (Pastikan kodenya utuh di dalam tanda petik)
GEMINI_API_KEY = "AQ.Ab8RN6IEWvky6PEWcSs5"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/proses', methods=['POST'])
def proses_video():
    data = request.json
    url = data.get('url')
    mode_cut = data.get('mode_cut', 'manual') # 'manual' atau 'auto'
    mulai = data.get('mulai', '00:00')      
    selesai = data.get('selesai', '00:30')  
    teks_hook = data.get('teks_hook', '') 
    mode_tampilan = data.get('mode', 'crop')
    
    output_download = "video_asli.mp4"
    output_potong = "video_potong.mp4"
    output_hasil = os.path.join(OUTPUT_DIR, "klip_vertikal.mp4")
    
    for f in [output_download, output_potong, output_hasil]:
        if os.path.exists(f): os.remove(f)

    try:
        # 1. Download video asli menggunakan yt-dlp
        import yt_dlp
        ydl_opts = {'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]', 'outtmpl': output_download}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            judul_video = info_dict.get('title', '')
            deskripsi_video = info_dict.get('description', '')

        # 2. FITUR AUTO CUT: Minta Gemini AI menentukan menit terbaik berdasarkan data video
        if mode_cut == 'auto':
            url_api = f"https://googleapis.com{GEMINI_API_KEY}"
            headers = {'Content-Type': 'application/json'}
            prompt_ai = (
                f"Video ini berjudul '{judul_video}' dengan deskripsi: '{deskripsi_video}'. "
                "Pilih satu segmen momen paling menarik sepanjang 30-45 detik untuk dijadikan video TikTok viral. "
                "Berikan jawaban HANYA dalam format JSON mentah seperti ini tanpa markdown: "
                '{"mulai": "01:20", "selesai": "01:55", "teks_hook": "Tulis judul hook video disini"}'
            )
            payload = {"contents": [{"parts": [{"text": prompt_ai}]}]}
            
            response = requests.post(url_api, headers=headers, json=payload)
            hasil_ai = response.json()
            teks_json = hasil_ai['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # Bersihkan jika AI nakal menyertakan tanda ```json
            teks_json = teks_json.replace("```json", "").replace("```", "").strip()
            data_auto = json.loads(teks_json)
            
            mulai = data_auto.get('mulai', '00:10')
            selesai = data_auto.get('selesai', '00:40')
            teks_hook = data_auto.get('teks_hook', 'Momen Terbaik! 🔥')

        # Penyesuaian format waktu untuk FFmpeg
        if mulai.count(':') == 1: mulai = f"00:{mulai}"
        if selesai.count(':') == 1: selesai = f"00:{selesai}"
        
        # 3. Potong durasi awal secara lokal
        cut_cmd = f"ffmpeg -i {output_download} -ss {mulai} -to {selesai} -c copy {output_potong} -y"
        subprocess.run(cut_cmd, shell=True, check=True)
        
        # 4. Potong Tampilan Vertikal (9:16)
        if mode_tampilan == "crop":
            crop_filter = "crop=ih*9/16:ih"
        else:
            crop_filter = "split[v1][v2];[v1]scale=ih*9/16:ih,boxblur=20[bg];[v2]scale=-1:ih[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,crop=ih*9/16:ih"
            
        if teks_hook:
            teks_aman = teks_hook.replace("'", "").replace('"', '')
            filter_full = f"{crop_filter},drawtext=text='{teks_aman}':fontcolor=white:fontsize=36:box=1:boxcolor=red@0.8:boxborderw=12:x=(w-tw)/2:y=150:enable='lte(t,4)'"
            ffmpeg_cmd = f"ffmpeg -i {output_potong} -vf \"{filter_full}\" -c:v libx264 -crf 23 -c:a aac {output_hasil} -y"
        else:
            ffmpeg_cmd = f"ffmpeg -i {output_potong} -vf \"{crop_filter}\" -c:v libx264 -crf 23 -c:a aac {output_hasil} -y"
            
        subprocess.run(ffmpeg_cmd, shell=True, check=True)
        
        if os.path.exists(output_download): os.remove(output_download)
        if os.path.exists(output_potong): os.remove(output_potong)
        
        return jsonify({
            "status": "Sukses", 
            "video_url": "/static/hasils/klip_vertikal.mp4", 
            "mulai_terpilih": mulai.replace("00:", ""), 
            "selesai_terpilih": selesai.replace("00:", ""),
            "teks_hook_terpilih": teks_hook
        })
        
    except Exception as e:
        return jsonify({"status": "Gagal", "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
