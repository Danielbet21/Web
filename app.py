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

# Tell Flask to use /static as public folder
app = Flask(__name__, static_folder="static", static_url_path="/static")

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
Generate a beautiful HTML email with inline CSS.
Include:
- Header: {location}
- 3 image cards with Google Maps links, titles, recommendations
- Soft background, rounded images, shadows
- Bottom: map image {map_image}, approve + reject buttons, feedback form.
- Approve button → <a href='http://localhost:5000/approve?id={record_id}'> styled green
- Reject button → <a href='http://localhost:5000/reject?id={record_id}'> styled red
- Feedback form → action='http://localhost:5000/reject', hidden input 'id'={record_id}, textarea 'adjustment'
Return only the HTML code, no explanations.
"""
    for i in range(3):
        maps_url = f"https://www.google.com/maps/search/?api=1&query={labels[i].replace(' ', '+')}+{location.replace(' ', '+')}"
        prompt += f"\n- Image {i+1}: {image_urls[i]}, Label: {labels[i]}, Recommendation: {recommendations[i]}, Maps URL: {maps_url}"
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
    record_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
    headers = {"Authorization": f"Bearer {AIRTABLE_API_KEY}"}
    record_resp = requests.get(record_url, headers=headers)
    record = record_resp.json()
    location = record["fields"].get("Location")
    email = record["fields"].get("Email")
    image_urls, captions = fetch_images(location)
    labels, recommendations = process_images_with_groq(image_urls, captions, location)
    map_image = get_static_map_with_markers(labels, location)
    html = generate_full_html_with_groq(location, image_urls, labels, recommendations, map_image, record_id)
    send_email(email, f"✅ Approved travel page for {location}", html)

    # ✅ Get absolute path to static/approved_html
    project_root = os.path.dirname(os.path.abspath(__file__))
    save_dir = os.path.join(project_root, "static", "approved_html")
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, f"{record_id}.html")

    # ✅ Save HTML file
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Saved HTML file to: {file_path}")

    # ✅ Construct public link
    html_link = f"http://localhost:5000/static/approved_html/{record_id}.html"

    # ✅ Update Airtable with link
    patch_data = {"fields": {"Status": "approved", "Notes": html_link}}
    patch_resp = requests.patch(record_url, headers={**headers, "Content-Type": "application/json"}, json=patch_data)

    if patch_resp.ok:
        return "✅ Approved and link saved to Airtable!"
    else:
        return f"❌ Approved but failed to save to Airtable: {patch_resp.text}"

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
    html = generate_full_html_with_groq(location, image_urls, labels, recommendations, map_image, record_id)
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