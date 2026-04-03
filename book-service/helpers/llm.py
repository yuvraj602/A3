import os

import requests


def call_gemini_api(api_key, prompt):
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    try:
        response = requests.post(url, json=body, timeout=30)
    except requests.RequestException as exc:
        print(f"Gemini API request error: {exc}")
        return None

    if response.status_code != 200:
        print(f"Gemini API returned status {response.status_code}: {response.text}")
        return None

    try:
        parsed = response.json()
    except ValueError as exc:
        print(f"Error parsing Gemini response: {exc}")
        return None

    return parsed.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text")


def fetch_and_store_summary(db_conn, isbn, title, author):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set. Skipping summary generation.")
        return

    prompt = (
        f'Write a 500-word summary of the book "{title}" by {author}. '
        + "If you are not familiar with this specific book, provide a plausible and informative "
        + "summary based on the title and author."
    )

    summary = call_gemini_api(api_key, prompt)
    if not summary:
        return

    cursor = db_conn.cursor()
    try:
        cursor.execute("UPDATE books SET summary = %s WHERE ISBN = %s", (summary, isbn))
        db_conn.commit()
        print(f"Summary stored for ISBN: {isbn}")
    finally:
        cursor.close()
