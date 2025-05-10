import os
import requests
import smtplib
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
For each of the 3 images below, give:
1) the correct landmark name (1-3 words)
2) a short travel recommendation (1-2 sentences)

If the image has no obvious landmark, make a smart guess or repeat the city name.

Images:
"""
    for i in range(3):
        prompt += f"- Caption: {captions[i]}, URL: {image_urls[i]}\n"
    prompt += """
Return as a numbered list with exactly three items.
Format:
1. Landmark Name | Recommendation text
"""
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
    return f"https://maps.googleapis.com/maps/api/staticmap?size=600x300&{markers}&key={GOOGLE_MAPS_API_KEY}"

def generate_full_html_with_groq(location, image_urls, labels, recommendations, map_image, record_id):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    prompt = f"""
Generate a beautiful, modern HTML email using inline CSS.

Requirements:
- Add a bold, stylish header with the city name: {location}.
- Show 3 image cards, each with:
    • the image as a clickable link to Google Maps (https://www.google.com/maps/search/?api=1&query=LANDMARK+CITY),
    • a beautiful title for the landmark,
    • a short recommendation below.
- Style the images with rounded corners, soft shadows, max-width ~300px.
- Use a soft background color or gradient.
- At the bottom, add:
    • a large map image: {map_image},
    • two side-by-side buttons:
        - green "Approve" button (http://localhost:5000/approve?id={record_id}),
        - red "Reject" button (http://localhost:5000/reject?id={record_id}),
    • a form with a textarea and submit button:
        → action: http://localhost:5000/reject
        → hidden input name='id' value='{record_id}'
        → textarea name='adjustment'
        → submit button label: 'Submit Adjustments'
        → style it clean, rounded, with soft shadow.
Important:
- Do NOT include comments, notes, or explanations in the HTML.
- Only return the HTML code.
"""
    for i in range(3):
        maps_url = f"https://www.google.com/maps/search/?api=1&query={labels[i].replace(' ', '+')}+{location.replace(' ', '+')}"
        prompt += f"\n- Image {i+1}: {image_urls[i]}, Label: {labels[i]}, Recommendation: {recommendations[i]}, Maps URL: {maps_url}"
    prompt += "\nReturn only the HTML code."
    data = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    response = requests.post(url, headers=headers, json=data)
    html = response.json()["choices"][0]["message"]["content"]
    return html

def generate_adjusted_html_with_groq(old_html, adjustment):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    prompt = f"""
Here’s the previous HTML email:
{old_html}

The user requested this adjustment:
{adjustment}

Regenerate the HTML email accordingly, improving the design as requested.
- Use inline CSS.
- Keep the layout, buttons, and form functional.
- Do NOT add comments or explanations — return only the updated HTML.
"""
    data = {
        "model": "llama3-70b-8192",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    response = requests.post(url, headers=headers, json=data)
    html = response.json()["choices"][0]["message"]["content"]
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
    adjustment = request.args.get("adjustment", "").strip()
    record_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    record_resp = requests.get(record_url, headers=headers)
    record = record_resp.json()
    location = record["fields"].get("Location")
    email = record["fields"].get("Email")
    image_urls, captions = fetch_images(location)
    labels, recommendations = process_images_with_groq(image_urls, captions, location)
    map_image = get_static_map_with_markers(labels, location)
    old_html = generate_full_html_with_groq(location, image_urls, labels, recommendations, map_image, record_id)
    html = generate_adjusted_html_with_groq(old_html, adjustment) if adjustment else old_html
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
        html = generate_full_html_with_groq(location, image_urls, labels, recommendations, map_image, record_id)
        send_email(email, f"Travel page for {location}", html)
    print("✅ Done sending all emails!")

if __name__ == "__main__":
    process_entries()
    app.run(host="0.0.0.0", port=5000)