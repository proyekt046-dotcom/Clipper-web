import os
import subprocess
from flask import Flask, render_template, request, jsonify
import yt_dlp
import google.generativeai as genai
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

OUTPUT_DIR = "static/hasils"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Tempelkan API Key panjang dari Google AI Studio milik Anda di dalam tanda petik ini
GOOGLE_API_KEY = "AQ.Ab8RN6IEWvky6PEWcSs5" 
genai.configure(api_key=GOOGLE_API_KEY)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/proses', methods=['POST'])
def proses_video():
    data = request.json
    url = data.get('url')
    mulai = data.get('mulai')      
    selesai = data.get('selesai')  
    teks_hook = data.get('teks_hook', '') 
    
    if mulai.count(':') == 1: mulai = f"00:{mulai}"
    if selesai.count(':') == 1: selesai = f"00:{selesai}"
    
    output_download = "video_asli.mp4"
    output_potong = "video_potong.mp4"
    output_hasil = os.path.join(OUTPUT_DIR, "klip_vertikal.mp4")
    
    for f in [output_download, output_potong, output_hasil]:
        if os.path.exists(f): os.remove(f)

    try:
        ydl_opts = {'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]', 'outtmpl': output_download}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        cut_cmd = f"ffmpeg -i {output_download} -ss {mulai} -to {selesai} -c copy {output_potong} -y"
        subprocess.run(cut_cmd, shell=True, check=True)
        
        video_file = genai.upload_file(path=output_potong)
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        prompt = "Analisis video ini. Jawab HANYA dengan satu kata di antara opsi ini: 'kiri', 'tengah', atau 'kanan' sesuai letak wajah pembicara dominan."
        response = model.generate_content([video_file, prompt])
        posisi_wajah = response.text.strip().lower()
        genai.delete_file(video_file.name)
        
        if "kiri" in posisi_wajah:
            crop_filter = "crop=ih*9/16:ih:0:0"
        elif "kanan" in posisi_wajah:
            crop_filter = "crop=ih*9/16:ih:in_w-out_w:0"
        else:
            crop_filter = "crop=ih*9/16:ih"
            
        if teks_hook:
            teks_aman = teks_hook.replace("'", "").replace('"', '')
            filter_full = f"{crop_filter},drawtext=text='{teks_aman}':fontcolor=white:fontsize=40:box=1:boxcolor=red@0.8:boxborderw=15:x=(w-tw)/2:y=150:enable='lte(t,3)'"
            ffmpeg_cmd = f"ffmpeg -i {output_potong} -vf \"{filter_full}\" -c:v libx264 -crf 23 -c:a aac {output_hasil} -y"
        else:
            ffmpeg_cmd = f"ffmpeg -i {output_potong} -vf \"{crop_filter}\" -c:v libx264 -crf 23 -c:a aac {output_hasil} -y"
            
        subprocess.run(ffmpeg_cmd, shell=True, check=True)
        
        if os.path.exists(output_download): os.remove(output_download)
        if os.path.exists(output_potong): os.remove(output_potong)
        
        return jsonify({"status": "Sukses", "video_url": "/static/hasils/klip_vertikal.mp4", "posisi_terdeteksi": posisi_wajah})
        
    except Exception as e:
        return jsonify({"status": "Gagal", "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
