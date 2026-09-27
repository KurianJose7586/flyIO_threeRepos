import requests
import json
import sys
import re

LLM_URL = "https://dev-flyio-ai-llm.flyio.ai"
LLM_KEY = "dev_shared_service_key_2026"
TARGET_URL = "https://en.wikivoyage.org/wiki/Jaipur"

def extract_text_from_html(html_content):
    # A simple regex-based HTML tag stripper
    # This removes all HTML tags and extracts just the text
    text = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def main():
    print(f"Fetching content directly from {TARGET_URL}...")
    try:
        resp = requests.get(TARGET_URL, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
        resp.raise_for_status()
        html_content = resp.text
    except Exception as e:
        print(f"Error fetching URL: {e}")
        sys.exit(1)
        
    print("Extracting raw text from HTML...")
    raw_text = extract_text_from_html(html_content)
    
    print(f"Extracted {len(raw_text)} characters of text. Pushing to LLM Store API in batches...")
    
    batch_size = 10000
    for i in range(0, len(raw_text), batch_size):
        chunk_text = raw_text[i:i+batch_size]
        print(f"Pushing batch {i//batch_size + 1}...")
        try:
            store_resp = requests.post(
                f"{LLM_URL}/v1/api/store",
                json={
                    "text": chunk_text,
                    "title": "Jaipur - Wikivoyage",
                    "source_url": TARGET_URL,
                    "destination": "Jaipur"
                },
                headers={"X-Service-API-Key": LLM_KEY}
            )
            store_resp.raise_for_status()
        except Exception as e:
            print(f"Error storing data: {e}")
            if 'store_resp' in locals() and store_resp is not None:
                print(store_resp.text)
            sys.exit(1)
            
    print("Success! All batches processed.")
    print("\nJaipur data is now in the Vector DB! You can now test it in Swagger.")

if __name__ == "__main__":
    main()
