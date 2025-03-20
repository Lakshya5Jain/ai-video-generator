# app.py 

import time
import threading
import uuid
import requests
import openai
from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
import sqlite3
from datetime import datetime
import dotenv  # NEW Import

dotenv.load_dotenv()  # Load environment variables from .env file

# Access keys securely
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AI_API_KEY = os.getenv("AI_API_KEY")
CREATOMATE_API_KEY = os.getenv("CREATOMATE_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL")
CREATOMATE_BASE_URL = os.getenv("CREATOMATE_BASE_URL")

app = Flask(__name__)


app.secret_key = 'your_secret_key_here'  # This key is used to sign session cookies and secure session data.

# Database for saving past videos
DATABASE = 'videos.db'

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS past_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            final_video_url TEXT NOT NULL,
            script_text TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def save_video_to_db(final_video_url, script_text, timestamp):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('INSERT INTO past_videos (final_video_url, script_text, timestamp) VALUES (?, ?, ?)',
              (final_video_url, script_text, timestamp))
    conn.commit()
    conn.close()

# Global dictionary to store processing progress (keyed by process ID)
progress_dict = {}

# Immediately create your DB table
with app.app_context():
    init_db()

def generate_script(topic):
    """Generate a TikTok-style script from ChatGPT based on the given topic."""
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    prompt = (
        f"Write a concise and clear script about the following topic: '{topic}'. "
        "The script should be suitable for text-to-speech, avoiding informal expressions, emojis, and overly complex sentences. "
        "Use punctuation to indicate natural pauses."
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful AI that writes scripts suitable for text-to-speech applications."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=300,
        temperature=0.7,
    )
    script = response.choices[0].message.content.strip()
    return script

def generate_video(user_text, voice_id, img_url):
    """Generate video using AI API and return the video URL."""
    headers = {
        'Authorization': f'Bearer {AI_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    data = {
        'img_url': img_url,
        'text': user_text,
        'voice_id': voice_id,
        'resolution': '320',
        'crop_head': False,
        'expressiveness': 0.7
    }
    response = requests.post(AI_BASE_URL, headers=headers, json=data)
    response_data = response.json()
    if response.status_code == 200 and 'job_id' in response_data:
        job_id = response_data['job_id']
        print(f"Video generation started. Job ID: {job_id}")
        status_url = f'https://infinity.ai/api/v2/generations/{job_id}'
        while True:
            status_response = requests.get(status_url, headers=headers)
            status_data = status_response.json()
            if status_response.status_code == 200:
                status = status_data.get('status')
                if status == 'completed':
                    print("Video generation completed!")
                    return status_data.get('video_url')
                elif status == 'failed':
                    print("Video generation failed.")
                    return None
                else:
                    print("Video generation in progress... Retrying in 10 seconds.")
            else:
                print("Error checking status:", status_response.status_code, status_response.text)
                return None
            time.sleep(10)
    else:
        print("Error starting video generation:", response.status_code, response_data)
        return None

def create_final_video(ai_video_url, supporting_video):
    """Use Creatomate API to merge the AI video with supporting media."""
    options = {
        'template_id': '236352ae-d17e-43ad-9aed-4f13004fe57d',
        "modifications": {
            "anchor": ai_video_url,
            "supporting_video": supporting_video
        },
    }
    headers = {
        'Authorization': f'Bearer {CREATOMATE_API_KEY}',
        'Content-Type': 'application/json',
    }
    response = requests.post(CREATOMATE_BASE_URL, headers=headers, json=options)
    if response.status_code == 202:
        render_data = response.json()[0]
        render_id = render_data['id']
        print(f"Render initiated. Render ID: {render_id}")
        print("Waiting for render to complete...")
        while True:
            status_response = requests.get(f'{CREATOMATE_BASE_URL}/{render_id}', headers=headers)
            if status_response.status_code == 200:
                status_data = status_response.json()
                render_status = status_data.get('status')
                if render_status == 'succeeded':
                    print("Render completed!")
                    return status_data.get('url')
                elif render_status == 'failed':
                    print("Render failed. Exiting.")
                    return None
                else:
                    print(f"Render status: {render_status}. Retrying in 5 seconds...")
                    time.sleep(5)
            else:
                print(f"Failed to check render status: {status_response.status_code}, {status_response.text}")
                return None
    else:
        print(f"Error: {response.status_code}, {response.text}")
        return None

def background_process(process_id, topic, supporting_video):
    """Run processing steps in the background while updating progress_dict and saving the final video."""
    try:
        # If no custom script is provided, generate one using GPT (using the topic)
        if not progress_dict[process_id]["script_text"]:
            progress_dict[process_id]["status"] = "Generating script..."
            progress_dict[process_id]["progress"] = 25
            script_text = generate_script(topic)
            progress_dict[process_id]["script_text"] = script_text
        else:
            progress_dict[process_id]["status"] = "Using custom script..."
            progress_dict[process_id]["progress"] = 25

        progress_dict[process_id]["status"] = "Generating AI video..."
        progress_dict[process_id]["progress"] = 50
        voice_id = progress_dict[process_id].get("voice_id", "LXVY607YcjqxFS3mcult")
        voice_media = progress_dict[process_id].get("voice_media", "https://6ammc3n5zzf5ljnz.public.blob.vercel-storage.com/inf2-image-uploads/image_8132d-DYy5ZM9i939tkiyw6ADf3oVyn6LivZ.png")
        ai_video_url = generate_video(progress_dict[process_id]["script_text"], voice_id, voice_media)
        if not ai_video_url:
            progress_dict[process_id]["status"] = "Failed to generate AI video."
            progress_dict[process_id]["progress"] = 100
            return
        progress_dict[process_id]["ai_video_url"] = ai_video_url

        progress_dict[process_id]["status"] = "Creating final video..."
        progress_dict[process_id]["progress"] = 75
        final_video_url = create_final_video(ai_video_url, supporting_video)
        if not final_video_url:
            progress_dict[process_id]["status"] = "Failed to create final video."
            progress_dict[process_id]["progress"] = 100
            return
        progress_dict[process_id]["final_video_url"] = final_video_url
        progress_dict[process_id]["status"] = "Completed!"
        progress_dict[process_id]["progress"] = 100

        # Save the final video details to the database
        timestamp = time.time()
        save_video_to_db(final_video_url, progress_dict[process_id]["script_text"], timestamp)
    except Exception as e:
        progress_dict[process_id]["status"] = f"Error: {str(e)}"
        progress_dict[process_id]["progress"] = 100

@app.template_filter('datetimeformat')
def datetimeformat(value):
    return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S')

@app.route("/", methods=["GET"])
def index():
    # Retrieve past videos (latest first)
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT final_video_url, script_text, timestamp FROM past_videos ORDER BY timestamp DESC')
    videos = [{'final_video_url': row[0], 'script_text': row[1], 'timestamp': row[2]} for row in c.fetchall()]
    conn.close()
    return render_template("index.html", videos=videos)

@app.route("/generate", methods=["POST"])
def generate():
    topic = request.form.get("topic")
    supporting_media = request.form.get("supporting_video")
    script_option = request.form.get("script_option", "gpt")

    if not supporting_media:
        supporting_media = ""

    if script_option == "custom":
        script_text = request.form.get("custom_script", "").strip()
        if not script_text:
            return "Please provide your custom script."
    else:
        if not topic:
            return "Please provide a topic/keyword for GPT script generation."
        script_text = ""  # An empty string signals to generate the script via GPT

    # Process voice selection and character media link
    voice_id = request.form.get("voice_id", "LXVY607YcjqxFS3mcult")
    voice_media_link = request.form.get("voice_media_link", "").strip()
    if voice_media_link == "":
        voice_media_link = "https://6ammc3n5zzf5ljnz.public.blob.vercel-storage.com/inf2-image-uploads/image_8132d-DYy5ZM9i939tkiyw6ADf3oVyn6LivZ.png"

    # Generate a unique process ID and initialize its progress state.
    process_id = str(uuid.uuid4())
    progress_dict[process_id] = {
        "progress": 0,
        "status": "Starting...",
        "final_video_url": None,
        "script_text": script_text,
        "voice_id": voice_id,
        "voice_media": voice_media_link
    }

    # Start the background processing in a separate thread.
    thread = threading.Thread(target=background_process, args=(process_id, topic, supporting_media))
    thread.start()

    # Redirect immediately to the loading page.
    return redirect(url_for("loading", pid=process_id))

@app.route("/loading")
def loading():
    pid = request.args.get("pid")
    if not pid:
        return redirect(url_for("index"))
    return render_template("loading.html", pid=pid)

@app.route("/progress")
def progress():
    pid = request.args.get("pid")
    if not pid or pid not in progress_dict:
        return jsonify({"error": "Invalid process ID"}), 400
    return jsonify(progress_dict[pid])

@app.route("/result")
def result():
    pid = request.args.get("pid")
    if not pid or pid not in progress_dict:
        return redirect(url_for("index"))
    data = progress_dict.get(pid)
    if data["progress"] < 100 or not data.get("final_video_url"):
        return "Processing not complete yet. Please refresh in a moment."
    return render_template("result.html", final_video_url=data["final_video_url"], script_text=data["script_text"])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
