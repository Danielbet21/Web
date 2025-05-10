import os
import requests
import smtplib
import random
from flask import Flask, request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = "Table%201"
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

app = Flask(__name__)

def get_airtable_records():
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    response = requests.get(url, headers=headers)
    records = response.json().get("records", [])
    return [r for r in records if r["fields"].get("Status", "").lower() == "pending"]

def fetch_images(location, count=3):
    url = f"https://api.unsplash.com/search/photos?query={location}&per_page={count}"
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    response = requests.get(url, headers=headers)
    results = response.json().get("results", [])
    image_urls, captions = [], []

    for img in results:
        image_urls.append(img["urls"]["regular"])
        alt = img["alt_description"] or "No caption available"
        captions.append(alt)

    while len(image_urls) < 3:
        image_urls.append("https://via.placeholder.com/300x200?text=No+Image")
        captions.append("No image available")

    return image_urls, captions

def process_images_with_groq(image_urls, captions, location):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    prompt = f"""
For each image below, give:
1) the correct landmark name (1-3 words)
2) a short travel recommendation (1-2 sentences)

Images:
"""
    for i in range(len(image_urls)):
        prompt += f"- Caption: {captions[i]}, URL: {image_urls[i]}\n"

    prompt += "\nReturn as a numbered list, like:\n1. Charles Bridge | Visit early in the morning for sunrise views.\n"

    data = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5
    }
    response = requests.post(url, headers=headers, json=data)
    text = response.json()["choices"][0]["message"]["content"]

    labels, recommendations = [], []
    lines = text.strip().split('\n')
    for line in lines:
        if '.' in line and '|' in line:
            parts = line.split('.', 1)[1].strip().split('|')
            if len(parts) == 2:
                labels.append(parts[0].strip())
                recommendations.append(parts[1].strip())
    return labels, recommendations

def get_static_map_with_markers(places, city):
    markers = '&'.join([f"markers={place.replace(' ', '+')},{city.replace(' ', '+')}" for place in places])
    map_url = f"https://maps.googleapis.com/maps/api/staticmap?size=600x300&{markers}&key={GOOGLE_MAPS_API_KEY}"
    return map_url

def random_color():
    return random.choice(["#FF6F61", "#6B5B95", "#88B04B", "#F7CAC9", "#92A8D1"])

def build_html(location, image_urls, labels, recommendations, map_image, record_id):
    header_color = random_color()
    button_approve_color = "#28a745"
    button_reject_color = "#dc3545"

    html = f"""
    <div style="font-family:sans-serif; text-align:center; background-color:#f9f9f9; padding:20px;">
        <h1 style="color:{header_color};">Travel Guide: {location}</h1>
        <div>
    """
    for i in range(3):
        html += f"""
            <img src="{image_urls[i]}" alt="{labels[i]}" style="max-width:300px; height:auto; border-radius:10px; margin:10px;">
            <p><b>{labels[i]}</b></p>
            <p style="color:#555;">{recommendations[i]}</p>
        """
    html += f"""
        </div>
        <h2 style="color:{header_color}; margin-top:30px;">Landmarks Map</h2>
        <img src="{map_image}" alt="Map of landmarks" onerror="this.src='https://via.placeholder.com/600x300?text=No+Map+Available';" style="max-width:600px; height:auto; border-radius:10px;">
        <div style="margin-top:30px;">
            <a href="http://localhost:5000/approve?id={record_id}" style="background:{button_approve_color}; color:#fff; padding:10px 20px; text-decoration:none; margin-right:10px; border-radius:5px;">Approve</a>
            <a href="http://localhost:5000/reject?id={record_id}" style="background:{button_reject_color}; color:#fff; padding:10px 20px; text-decoration:none; border-radius:5px;">Reject</a>
        </div>
    </div>
    """
    return html

def send_email(recipient, subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient
    msg.attach(MIMEText(body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, recipient, msg.as_string())

@app.route("/approve")
def approve():
    record_id = request.args.get("id")
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}", "Content-Type": "application/json"}
    data = {"fields": {"Status": "approved"}}
    response = requests.patch(url, headers=headers, json=data)
    return "✅ Approved!" if response.ok else f"❌ Failed: {response.text}"

@app.route("/reject")
def reject():
    record_id = request.args.get("id")
    record_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    record_resp = requests.get(record_url, headers=headers)
    record = record_resp.json()

    location = record["fields"].get("Location")
    email = record["fields"].get("Email")

    image_urls, captions = fetch_images(location)
    labels, recommendations = process_images_with_groq(image_urls, captions, location)
    map_image = get_static_map_with_markers(labels, location)
    html = build_html(location, image_urls, labels, recommendations, map_image, record_id)
    send_email(email, f"Updated travel page for {location}", html)

    return "🔁 Rejected → new email sent!"

def process_entries():
    print("⏳ Processing entries...")
    records = get_airtable_records()
    for record in records:
        location = record["fields"].get("Location")
        email = record["fields"].get("Email")
        record_id = record["id"]
        print(f"➡️ Processing {location} for {email}")
        image_urls, captions = fetch_images(location)
        labels, recommendations = process_images_with_groq(image_urls, captions, location)
        map_image = get_static_map_with_markers(labels, location)
        html = build_html(location, image_urls, labels, recommendations, map_image, record_id)
        send_email(email, f"Travel page for {location}", html)
    print("✅ Done sending all emails!")

if __name__ == "__main__":
    process_entries()
    app.run(host="0.0.0.0", port=5000)