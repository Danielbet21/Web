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
    image_urls = []
    captions = []
    for img in results:
        image_urls.append(img["urls"]["regular"])
        captions.append(img["alt_description"] or "No caption available")
    while len(image_urls) < 3:
        image_urls.append("https://via.placeholder.com/300x200?text=No+Image")
        captions.append("No image available")
    return image_urls, captions

def get_static_map(location):
    google_api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    return f"https://maps.googleapis.com/maps/api/staticmap?center={location.replace(' ', '+')}&zoom=12&size=600x300&key={google_api_key}"

def random_color():
    return random.choice(["#FF6F61", "#6B5B95", "#88B04B", "#F7CAC9", "#92A8D1"])

def build_html(location, image_urls, captions, map_image, record_id):
    header_color = random_color()
    button_approve_color = "#28a745"
    button_reject_color = "#dc3545"
    return f"""
    <div style="font-family:sans-serif; text-align:center; background-color:#f9f9f9; padding:20px;">
        <h1 style="color:{header_color};">Travel Guide: {location}</h1>
        <div>
            <img src="{image_urls[0]}" alt="{captions[0]}" style="max-width:300px; height:auto; border-radius:10px; margin:10px;">
            <p>{captions[0]}</p>
            <img src="{image_urls[1]}" alt="{captions[1]}" style="max-width:300px; height:auto; border-radius:10px; margin:10px;">
            <p>{captions[1]}</p>
            <img src="{image_urls[2]}" alt="{captions[2]}" style="max-width:300px; height:auto; border-radius:10px; margin:10px;">
            <p>{captions[2]}</p>
        </div>
        <h2 style="color:{header_color}; margin-top:30px;">Map of {location}</h2>
        <img src="{map_image}" alt="Map of {location}" onerror="this.src='https://via.placeholder.com/600x300?text=No+Map+Available';" style="max-width:600px; height:auto; border-radius:10px;">
        <div style="margin-top:30px;">
            <a href="http://localhost:5000/approve?id={record_id}" style="background:{button_approve_color}; color:#fff; padding:10px 20px; text-decoration:none; margin-right:10px; border-radius:5px;">Approve</a>
            <a href="http://localhost:5000/reject?id={record_id}" style="background:{button_reject_color}; color:#fff; padding:10px 20px; text-decoration:none; border-radius:5px;">Reject</a>
        </div>
    </div>
    """

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
    # Get record details from Airtable
    record_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    record_resp = requests.get(record_url, headers=headers)
    record = record_resp.json()

    location = record["fields"].get("Location")
    email = record["fields"].get("Email")

    # Generate NEW images, NEW colors, NEW email body
    image_urls, captions = fetch_images(location)
    map_image = get_static_map(location)
    html = build_html(location, image_urls, captions, map_image, record_id)

    # Send updated email (status stays "pending" in Airtable)
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
        map_image = get_static_map(location)
        html = build_html(location, image_urls, captions, map_image, record_id)
        send_email(email, f"Travel page for {location}", html)
    print("✅ Done sending all emails!")

if __name__ == "__main__":
    process_entries()
    app.run(host="0.0.0.0", port=5000)